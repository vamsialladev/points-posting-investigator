"""The few scenario functions that need a real Kafka broker and schema registry. Kept thin; tested on the stack.

- Valid events go through the pipeline's own checkout producer (ADR-0017), so a send that Kafka didn't take raises.
- Bad events (S01) are produced raw, with a delivery check.
- Lag is read by a consumer that never subscribes: it joins no group and commits nothing.
- The dead-letter topic is scanned from the start to its end offsets by a consumer that is only assigned, with its
  own throwaway group ID, and never commits.
- `join_group` is the one deliberate disturbance (S14): an extra member of the posting group that polls, takes
  partitions, processes nothing and commits nothing, until it leaves.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from typing import Any

from confluent_kafka import Consumer, KafkaError, Producer, TopicPartition
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroSerializer
from confluent_kafka.serialization import MessageField, SerializationContext

from app.ops import lag
from app.pipeline import kafka_auth, schemas, topics, trace
from app.pipeline.producer import CheckoutProducer, make_checkout_producer
from app.scenarios.stack import Kafka

SCAN_TIMEOUT_SECONDS = 30.0


def build(bootstrap: str, registry_url: str, posting_group: str) -> Kafka:
    bootstrap = bootstrap.replace("localhost", "127.0.0.1")
    registry = SchemaRegistryClient({"url": registry_url.replace("://localhost", "://127.0.0.1"), "timeout": 10})
    # The scenario tool breaks the local stack on purpose, so it acts as the broker's admin (ADR-0020).
    base = kafka_auth.client_config(kafka_auth.ADMIN, bootstrap)
    checkout = CheckoutProducer(make_checkout_producer(bootstrap, principal=kafka_auth.ADMIN), registry)
    serializer = AvroSerializer(registry, schemas.latest(topics.CHECKED_OUT))
    raw = Producer({**base, "acks": "all", "enable.idempotence": True})
    lag_reader = Consumer({**base, "group.id": posting_group, "enable.auto.commit": False})

    def serialize(record: dict[str, Any]) -> bytes:
        value = serializer(record, SerializationContext(topics.CHECKED_OUT, MessageField.VALUE))
        if value is None:
            raise ValueError("the record serialized to nothing")
        return bytes(value)

    def send_valid(record: dict[str, Any]) -> None:
        checkout.send(record)  # raises DeliveryFailed unless Kafka took it

    def send_raw(key: bytes, value: bytes, headers: dict[str, str]) -> None:
        errors: list[KafkaError] = []
        raw.produce(
            topics.CHECKED_OUT,
            key=key,
            value=value,
            headers=list({**headers, "traceparent": trace.new_traceparent()}.items()),
            on_delivery=lambda error, _message: errors.append(error) if error else None,
        )
        if raw.flush(30) or errors:
            raise RuntimeError(f"a raw event was not delivered: {errors[0].name() if errors else 'still queued'}")

    def dead_letter_event_ids() -> set[str]:
        return scan_header(base, topics.DLQ, "event_id")

    def join_group(group: str) -> Callable[[], None]:
        consumer = Consumer(
            {
                **base,
                "group.id": group,
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
                "enable.auto.offset.store": False,
            }
        )
        consumer.subscribe([topics.CHECKED_OUT])
        stop = threading.Event()

        def poll() -> None:
            while not stop.is_set():
                consumer.poll(0.2)  # takes its partitions and drops what it reads: nothing is committed

        thread = threading.Thread(target=poll, name="scenario-group-flap", daemon=True)
        thread.start()

        def leave() -> None:
            stop.set()
            thread.join(timeout=10)
            consumer.close()

        return leave

    return Kafka(
        send_valid=send_valid,
        send_raw=send_raw,
        serialize=serialize,
        lag=lambda: lag.total(lag.read(lag_reader, topics.CHECKED_OUT)),
        dead_letter_event_ids=dead_letter_event_ids,
        join_group=join_group,
    )


def scan_header(base: dict[str, Any], topic: str, header: str, timeout: float = SCAN_TIMEOUT_SECONDS) -> set[str]:
    """Every value of `header` on `topic`, from the first offset to the end offsets seen when the scan starts.
    `base` is the client's connection settings (`kafka_auth.client_config`)."""
    consumer = Consumer(
        {
            **base,
            "group.id": f"scenario-scan-{uuid.uuid4().hex[:10]}",  # assigned, never subscribed: no group is formed
            "enable.auto.commit": False,
            "enable.partition.eof": False,
        }
    )
    try:
        metadata = consumer.list_topics(topic, timeout=10).topics.get(topic)
        if metadata is None or metadata.error is not None:
            raise LookupError(f"topic {topic!r} is not readable")
        ends: dict[int, int] = {}
        assignment = []
        for partition in metadata.partitions:
            low, high = consumer.get_watermark_offsets(TopicPartition(topic, partition), timeout=10, cached=False)
            if high > low:
                ends[partition] = high
                assignment.append(TopicPartition(topic, partition, low))
        found: set[str] = set()
        if not assignment:
            return found
        consumer.assign(assignment)
        deadline = threading.Event()
        timer = threading.Timer(timeout, deadline.set)
        timer.start()
        try:
            while ends:
                if deadline.is_set():
                    raise TimeoutError(f"scanning {topic} took longer than {timeout:g} s")
                message = consumer.poll(1.0)
                if message is None or message.error():
                    continue
                partition, offset = message.partition(), message.offset()
                if partition is None or offset is None:
                    continue
                headers: list[tuple[str, bytes | None]] = message.headers() or []  # type: ignore[assignment]
                for name, value in headers:
                    if name == header and value is not None:
                        found.add(value.decode("utf-8", "replace"))
                if offset + 1 >= ends.get(partition, 0):
                    ends.pop(partition, None)
        finally:
            timer.cancel()
        return found
    finally:
        consumer.close()
