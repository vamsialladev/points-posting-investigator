"""Helpers for the relay's real-stack tests: write outbox rows as the posting service would, run relays, read Kafka."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from confluent_kafka import Consumer, TopicPartition
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroDeserializer
from confluent_kafka.serialization import MessageField, SerializationContext
from sqlalchemy import Engine, insert, select, text

from app.pipeline import schemas, topics, trace
from app.pipeline.relay import AvroPayloadSerializer, OutboxStore, Relay, RelayConfig, RelayMetrics, make_producer
from app.pipeline.tables import outbox


def payload(member: str, seq: int) -> dict[str, Any]:
    """A valid points.posted record (synthetic). `stay_points` carries the sequence number, so order is checkable."""
    return {
        "event_id": str(uuid.uuid4()),
        "source_event_id": str(uuid.uuid4()),
        "ledger_entry_id": f"L-{seq:07d}",
        "tenant": "hg-demo",
        "member_number": member,
        "stay_id": f"BR-{seq % 10000:04d}",
        "revision": 1,
        "stay_points": seq,
        "credited_points": seq,
        "posted_at": 1_763_380_800_000 + seq,
        "correlation_id": f"corr-{member}-{seq}",
    }


@dataclass(frozen=True)
class Written:
    id: int
    member: str
    seq: int
    event_id: str
    traceparent: str


def write_rows(
    writer: Engine, topic: str, plan: Iterable[tuple[str, int]], poison: set[int] | None = None
) -> list[Written]:
    """Insert outbox rows as the posting service role, in the order given. `poison` seqs lose a required field."""
    written = []
    with writer.begin() as conn:
        for member, seq in plan:
            record = payload(member, seq)
            if poison and seq in poison:
                del record["ledger_entry_id"]  # the Avro serializer refuses this every time
            tp = trace.new_traceparent()
            row_id = conn.execute(
                insert(outbox)
                .values(
                    topic=topic,
                    message_key=member,
                    payload=record,
                    headers={"correlation_id": record["correlation_id"], "schema_version": "1"},
                    trace_context={"traceparent": tp},
                )
                .returning(outbox.c.id)
            ).scalar_one()
            written.append(Written(row_id, member, seq, record["event_id"], tp))
    return written


def make_relay(
    relay_id: str,
    kafka: str,
    registry: SchemaRegistryClient,
    engine: Engine,
    topic: str,
    *,
    fault: Callable[[str], None] | None = None,
    before_produce: Callable[[Any], None] | None = None,
    **config: Any,
) -> Relay:
    cfg = RelayConfig(relay_id=relay_id, **{"backoff_base": 0.05, "backoff_cap": 0.2, **config})
    serializer = AvroPayloadSerializer(registry, {topic: schemas.latest(topics.POINTS_POSTED)})
    return Relay(
        OutboxStore(engine),
        make_producer(kafka, cfg.delivery_timeout),
        serializer,
        cfg,
        metrics=RelayMetrics(),
        fault=fault,
        before_produce=before_produce,
    )


def drain(relays: list[Relay], done: Callable[[], bool], timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while not done():
        if time.monotonic() > deadline:
            raise AssertionError(f"not done within {timeout} s")
        for relay in relays:
            relay.run_once()
        time.sleep(0.02)


def open_rows(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(text("SELECT count(*) FROM outbox WHERE status IN ('pending', 'in_flight')")).scalar_one()
        )


def rows_by_id(engine: Engine) -> dict[int, dict[str, Any]]:
    with engine.connect() as conn:
        return {r.id: dict(r._mapping) for r in conn.execute(select(outbox))}


@dataclass(frozen=True)
class Received:
    partition: int
    offset: int
    key: str
    value: dict[str, Any]
    headers: dict[str, str]


def read_topic(
    kafka: str, registry: SchemaRegistryClient, topic: str, at_least: int, timeout: float = 60.0
) -> list[Received]:
    """Every message on the topic, in (partition, offset) order. After `at_least` arrive it keeps reading for 3 s more,
    so a duplicate published late is still counted."""
    consumer = Consumer(
        {
            "bootstrap.servers": kafka,
            "group.id": f"test-read-{uuid.uuid4().hex[:8]}",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    deserialize = AvroDeserializer(registry)
    consumer.assign([TopicPartition(topic, p, 0) for p in range(3)])
    got: list[Received] = []
    deadline, grace_end = time.monotonic() + timeout, None
    try:
        while time.monotonic() < (grace_end or deadline):
            message = consumer.poll(0.5)
            if message is not None and message.error() is None:
                value = deserialize(message.value(), SerializationContext(topic, MessageField.VALUE))
                headers = {k: v.decode() for k, v in (message.headers() or [])}
                got.append(Received(message.partition(), message.offset(), message.key().decode(), value, headers))
            if grace_end is None and len(got) >= at_least:
                grace_end = time.monotonic() + 3.0
    finally:
        consumer.close()
    return sorted(got, key=lambda m: (m.partition, m.offset))


def per_member_order(received: list[Received]) -> dict[str, list[int]]:
    """stay_points (= the sequence number) per member, in partition order, first copy of each event only."""
    seen: set[str] = set()
    order: dict[str, list[int]] = {}
    for message in received:
        if message.value["event_id"] in seen:
            continue
        seen.add(message.value["event_id"])
        order.setdefault(message.key, []).append(message.value["stay_points"])
    return order
