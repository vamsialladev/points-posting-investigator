"""Evidence from Kafka, read with the `investigator` login: events, dead letters and the posting group's lag.

- A reader is only ever **assigned** to partitions. It never subscribes, so it joins no group, and it never
  commits. The broker would refuse a commit or a write from this login anyway (ADR-0021).
- An event's evidence carries where it is (topic, partition, offset), the broker's timestamp, the headers that
  identify it, and a few fields of the event itself, among them `occurred_at`: the producer's own clock. Comparing
  that with the broker's timestamp is the only way to see a producer's clock skew (scenario S13).
- The body of an event that can't be decoded is not returned, only the fact that it couldn't be.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.evidence.model import Evidence, evidence
from app.ops import lag

IDENTITY_HEADERS = ("event_id", "schema_version", "correlation_id")
FAILURE_HEADERS = (
    "error_class",
    "error_detail",
    "attempt",
    "original_topic",
    "original_partition",
    "original_offset",
    "first_failed_at",
    "last_failed_at",
)
EVENT_FIELDS = ("stay_id", "member_number", "revision")  # plus event_id and occurred_at, handled below
DEFAULT_LIMIT = 500
MAX_LIMIT = 5000
Decode = Callable[[bytes, str], dict[str, Any]]


def describe_message(topic: str, message: Any, decode: Decode | None, dead_letter: bool) -> Evidence:
    """One Kafka message as evidence. `message` is a confluent-kafka Message (or a test double with its methods)."""
    headers = {
        name: (value.decode("utf-8", "replace") if value is not None else None)
        for name, value in message.headers() or []
    }
    kind_of_time, millis = message.timestamp()
    broker_at = datetime.fromtimestamp(millis / 1000, UTC) if kind_of_time and millis and millis > 0 else None
    key = message.key()
    data: dict[str, Any] = {
        "topic": topic,
        "partition": message.partition(),
        "offset": message.offset(),
        "key": key.decode("utf-8", "replace") if key is not None else None,
    }
    wanted = IDENTITY_HEADERS + (FAILURE_HEADERS if dead_letter else ())
    data.update({name: headers[name] for name in wanted if name in headers})
    if decode is not None:
        try:
            record = decode(message.value(), topic)
            data.setdefault("event_id", record.get("event_id"))
            for name in EVENT_FIELDS:
                data[name] = record.get(name)
            occurred = record.get("occurred_at")
            data["occurred_at"] = occurred.isoformat() if isinstance(occurred, datetime) else occurred
            if isinstance(occurred, datetime) and broker_at is not None:
                # Positive: the producer's clock is ahead of the broker's.
                data["occurred_minus_broker_seconds"] = round((occurred - broker_at).total_seconds(), 3)
        except Exception as exc:  # undecodable: say so, and never return the bytes
            data["decoded"] = False
            data["decode_error"] = type(exc).__name__
        else:
            data["decoded"] = True
    kind = "dead_letter" if dead_letter else "event"
    return evidence(kind, f"{topic}/{message.partition()}@{message.offset()}", broker_at, **data)


class TopicReader:
    def __init__(self, base: dict[str, Any], decode: Decode | None = None, group: str | None = None) -> None:
        """`base`: the client's connection settings (`kafka_auth.client_config("investigator", ...)`).
        `group`: only used to read that group's committed offsets for the lag; nothing is ever committed to it."""
        self.base, self.decode, self.group = dict(base), decode, group

    def _consumer(self, group: str) -> Any:
        from confluent_kafka import Consumer

        return Consumer({**self.base, "group.id": group, "enable.auto.commit": False, "enable.partition.eof": False})

    def messages(
        self, topic: str, *, dead_letter: bool = False, limit: int = DEFAULT_LIMIT, timeout: float = 30.0
    ) -> tuple[list[Evidence], bool]:
        """The newest `limit` messages of every partition, oldest first. (items, whether older ones were left out)."""
        from confluent_kafka import TopicPartition

        if not 1 <= limit <= MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
        consumer = self._consumer(f"evidence-read-{uuid.uuid4().hex[:10]}")  # assigned only: no group is formed
        try:
            metadata = consumer.list_topics(topic, timeout=10).topics.get(topic)
            if metadata is None or metadata.error is not None:
                raise LookupError(f"topic {topic!r} is not readable")
            ends: dict[int, int] = {}
            assignment, left_out = [], False
            for partition in sorted(metadata.partitions):
                low, high = consumer.get_watermark_offsets(TopicPartition(topic, partition), timeout=10, cached=False)
                start = max(low, high - limit)
                left_out = left_out or start > low
                if high > start:
                    ends[partition] = high
                    assignment.append(TopicPartition(topic, partition, start))
            found: list[Evidence] = []
            if not assignment:
                return found, left_out
            consumer.assign(assignment)
            expired = threading.Event()
            timer = threading.Timer(timeout, expired.set)
            timer.start()
            try:
                while ends:
                    if expired.is_set():
                        raise TimeoutError(f"reading {topic} took longer than {timeout:g} s")
                    message = consumer.poll(1.0)
                    if message is None or message.error():
                        continue
                    partition, offset = message.partition(), message.offset()
                    if partition is None or offset is None:
                        continue
                    found.append(describe_message(topic, message, self.decode, dead_letter))
                    if offset + 1 >= ends.get(partition, 0):
                        ends.pop(partition, None)
            finally:
                timer.cancel()
            found.sort(key=lambda item: (item.data["partition"], item.data["offset"]))
            return found, left_out
        finally:
            consumer.close()

    def lag(self, topic: str) -> list[Evidence]:
        """The group's lag per partition, read now. Lag has no history: this is one moment."""
        if not self.group:
            raise ValueError("a group is needed to read lag")
        consumer = self._consumer(self.group)  # never subscribed or assigned: it joins nothing
        try:
            now = datetime.now(UTC)
            return [
                evidence(
                    "lag",
                    f"{self.group}/{row.topic}/{row.partition}@{now.strftime('%Y%m%dT%H%M%S')}",
                    now,
                    group=self.group,
                    topic=row.topic,
                    partition=row.partition,
                    committed=row.committed,
                    low=row.low,
                    high=row.high,
                    lag=row.lag,
                )
                for row in lag.read(consumer, topic)
            ]
        finally:
            consumer.close()
