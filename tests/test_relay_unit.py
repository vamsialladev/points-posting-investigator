"""The outbox relay's rules and loop, offline (ADR-0014). The real-Kafka/Postgres behaviour is test_relay_kafka.py."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from confluent_kafka import KafkaError, KafkaException
from confluent_kafka.serialization import SerializationError

from app.pipeline import trace
from app.pipeline.relay import (
    ClaimedRow,
    ErrorClass,
    Failure,
    OutboxStats,
    Relay,
    RelayConfig,
    RelayCrash,
    RelayMetrics,
    backoff_delay,
    classify,
    failure_outcome,
)

TP = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"


# ---------- backoff, classes, outcomes ----------


def test_backoff_doubles_with_jitter_and_stops_at_the_cap():
    low = [backoff_delay(n, base=1.0, cap=60.0, rand=lambda: 0.0) for n in range(1, 9)]
    high = [backoff_delay(n, base=1.0, cap=60.0, rand=lambda: 1.0) for n in range(1, 9)]
    assert low == [0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]  # half the step ...
    assert high == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]  # ... up to the full step, never above the cap


def test_backoff_rejects_nonsense():
    with pytest.raises(ValueError):
        backoff_delay(0, base=1.0, cap=60.0)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (KafkaError(KafkaError._MSG_TIMED_OUT), ErrorClass.TRANSIENT),
        (KafkaError(KafkaError._TRANSPORT), ErrorClass.TRANSIENT),
        (KafkaError(KafkaError._ALL_BROKERS_DOWN), ErrorClass.TRANSIENT),
        (KafkaException(KafkaError(KafkaError._TRANSPORT)), ErrorClass.TRANSIENT),
        (BufferError("queue full"), ErrorClass.TRANSIENT),
        (KafkaError(KafkaError.MSG_SIZE_TOO_LARGE), ErrorClass.PERMANENT),
        (SerializationError("missing field"), ErrorClass.PERMANENT),
        (ValueError("bad payload"), ErrorClass.PERMANENT),
    ],
)
def test_classify(error, expected):
    assert classify(error) is expected


CFG = RelayConfig(relay_id="r1", max_attempts=5)


def test_a_transient_failure_never_counts_toward_dead():
    # A Kafka outage isn't a poison row: 60 s of "brokers down" must not dead-letter good messages.
    for attempts in (0, 4, 100):
        assert failure_outcome(attempts, ErrorClass.TRANSIENT, CFG) == ("pending", attempts)


def test_a_permanent_failure_counts_and_dead_letters_at_max_attempts():
    assert failure_outcome(0, ErrorClass.PERMANENT, CFG) == ("pending", 1)
    assert failure_outcome(3, ErrorClass.PERMANENT, CFG) == ("pending", 4)
    assert failure_outcome(4, ErrorClass.PERMANENT, CFG) == ("dead", 5)


def test_config_validates():
    with pytest.raises(ValueError):
        RelayConfig(relay_id="")
    with pytest.raises(ValueError):
        RelayConfig(relay_id="r", max_attempts=0)
    with pytest.raises(ValueError):
        RelayConfig(relay_id="r", lease_seconds=0)


# ---------- trace context ----------


def test_traceparent_helpers():
    assert trace.is_valid(TP)
    assert not trace.is_valid("00-" + "0" * 32 + "-b7ad6b7169203331-01")
    assert not trace.is_valid("garbage") and not trace.is_valid(None)
    child = trace.child(TP)
    assert trace.trace_id(child) == trace.trace_id(TP) and child != TP
    assert trace.is_valid(trace.child(None))  # no parent: a new trace
    assert trace.context_from_headers({"traceparent": TP, "tracestate": "x=1"}) == {
        "traceparent": TP,
        "tracestate": "x=1",
    }
    assert trace.context_from_headers({"traceparent": "bad"}) == {}
    out = trace.kafka_headers({"traceparent": TP, "tracestate": "x=1"})
    assert trace.trace_id(out["traceparent"]) == trace.trace_id(TP) and out["tracestate"] == "x=1"


# ---------- the loop, with fakes ----------


@dataclass
class FakeStore:
    rows: list[ClaimedRow]
    published: list[int] = field(default_factory=list)
    failures: list[Failure] = field(default_factory=list)
    claims: int = 0

    def claim(self, relay_id: str, limit: int, lease_seconds: float) -> list[ClaimedRow]:
        self.claims += 1
        taken, self.rows = self.rows[:limit], self.rows[limit:]
        return taken

    def mark_published(self, relay_id: str, ids: list[int]) -> int:
        self.published += ids
        return len(ids)

    def mark_failed(self, relay_id: str, failures: list[Failure], config: RelayConfig) -> int:
        self.failures += failures
        return len(failures)

    def stats(self) -> OutboxStats:
        return OutboxStats(unpublished=len(self.rows), dead=0, oldest_unpublished_age_seconds=0.0)


@dataclass
class FakeMessage:
    topic: str
    key: bytes


class FakeProducer:
    def __init__(self, error_for: dict[int, KafkaError] | None = None, available: bool = True) -> None:
        self.error_for = error_for or {}
        self.available = available
        self.sent: list[tuple[str, bytes, bytes, dict[str, str]]] = []
        self._pending: list[tuple[object, KafkaError | None, FakeMessage]] = []

    def produce(self, topic, key, value, headers, on_delivery):
        self.sent.append((topic, key, value, dict(headers)))
        row_id = int(dict(headers)["outbox_id"])
        self._pending.append((on_delivery, self.error_for.get(row_id), FakeMessage(topic, key)))

    def flush(self, timeout):
        for callback, error, message in self._pending:
            callback(error, message)
        self._pending = []
        return 0

    def list_topics(self, timeout):
        if not self.available:
            raise KafkaException(KafkaError(KafkaError._TRANSPORT))
        return object()


def row(n: int, key: str = "GR-00001") -> ClaimedRow:
    return ClaimedRow(
        id=n,
        topic="points.posted",
        message_key=key,
        payload={"event_id": f"e{n}"},
        headers={"correlation_id": f"c{n}", "schema_version": "1"},
        trace_context={"traceparent": TP},
        attempts=0,
    )


def serialize(topic: str, payload: dict) -> bytes:
    if payload.get("poison"):
        raise SerializationError("missing required field")
    return repr(sorted(payload.items())).encode()


def make(store, producer, **kwargs):
    return Relay(store, producer, serialize, RelayConfig(relay_id="r1"), metrics=RelayMetrics(), **kwargs)


def test_delivered_rows_are_marked_published_with_trace_and_ids_in_headers():
    store, producer = FakeStore([row(1), row(2, "GR-00002")]), FakeProducer()
    result = make(store, producer).run_once()
    assert (result.claimed, result.published, result.failed) == (2, 2, 0)
    assert store.published == [1, 2]
    topic, key, _, headers = producer.sent[0]
    assert (topic, key) == ("points.posted", b"GR-00001")
    assert headers["outbox_id"] == "1" and headers["event_id"] == "e1" and headers["correlation_id"] == "c1"
    assert trace.trace_id(headers["traceparent"]) == trace.trace_id(TP)


def test_delivery_errors_and_serializer_errors_are_failures_with_their_class():
    poison = ClaimedRow(**{**row(3).__dict__, "payload": {"poison": True}})
    store = FakeStore([row(1), row(2), poison])
    producer = FakeProducer(error_for={2: KafkaError(KafkaError._MSG_TIMED_OUT)})
    metrics = RelayMetrics()
    result = Relay(store, producer, serialize, RelayConfig(relay_id="r1"), metrics=metrics).run_once()
    assert store.published == [1]
    assert {(f.row_id, f.error_class) for f in store.failures} == {(2, ErrorClass.TRANSIENT), (3, ErrorClass.PERMANENT)}
    assert (result.published, result.failed) == (1, 2)
    assert "outbox_publish_failures_total" in metrics.render().decode()


def test_no_claim_while_the_broker_is_unreachable():
    store = FakeStore([row(1)])
    result = make(store, FakeProducer(available=False)).run_once()
    assert result.skipped_broker_down and store.claims == 0 and store.rows  # nothing claimed, nothing leased


@pytest.mark.parametrize("point", ["after_claim", "after_publish_before_mark"])
def test_a_crash_leaves_rows_unmarked(point):
    store, producer = FakeStore([row(1)]), FakeProducer()

    def crash(where: str) -> None:
        if where == point:
            raise RelayCrash(where)

    with pytest.raises(RelayCrash):
        make(store, producer, fault=crash).run_once()
    assert store.published == [] and store.failures == []
    assert len(producer.sent) == (1 if point == "after_publish_before_mark" else 0)


def test_metrics_render_the_stats():
    metrics = RelayMetrics()
    metrics.observe(OutboxStats(unpublished=3, dead=1, oldest_unpublished_age_seconds=12.5))
    text = metrics.render().decode()
    assert "outbox_unpublished_rows 3.0" in text
    assert "outbox_dead_rows 1.0" in text
    assert "outbox_oldest_unpublished_age_seconds 12.5" in text
