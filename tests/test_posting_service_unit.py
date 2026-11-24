"""PostingService's decisions, offline, with fakes for the store, the ledger and the dead-letter publisher.

The store's SQL (one transaction, ON CONFLICT) and everything against real Kafka and Postgres is tested in
test_posting_kafka.py. Here: what the service decides for each kind of message, and what it passes on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import pytest

from app.pipeline import trace
from app.pipeline.events import validate
from app.pipeline.ledger_client import Credited, LedgerPermanent, LedgerTransient
from app.pipeline.posting import IncomingMessage, Outcome, PostingService, outbox_payload
from app.pipeline.producer import CheckoutProducer, build_event, synthetic_events

TP = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"


@dataclass
class FakeStore:
    posted: bool = False
    new: bool = True
    writes: list = field(default_factory=list)

    def already_posted(self, event):
        return self.posted

    def write(self, event, entry_id, trace_context, fault=None):
        self.writes.append((event.event_id, entry_id, dict(trace_context)))
        return self.new


@dataclass
class FakeLedger:
    result: object = field(default_factory=lambda: Credited("L-0000042", False))
    calls: list = field(default_factory=list)

    def credit(self, key, member_number, stay_id, points, correlation_id):
        self.calls.append((key, member_number, stay_id, points))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@dataclass
class FakeDeadLetters:
    sent: list = field(default_factory=list)

    def publish(self, message, error_class, detail, attempts=1):
        self.sent.append((message.offset, error_class))


RECORD = build_event(
    member_number="GR-00001",
    stay_id="BR-0001",
    check_in=date(2026, 11, 14),
    nights=3,
    room_rate_cents=45_000,
    occurred_at=datetime(2026, 11, 17, 12, tzinfo=UTC),
)


def message(value=b"avro", **header_changes):
    headers = {"event_id": RECORD["event_id"], "schema_version": "1", "traceparent": TP, **header_changes}
    return IncomingMessage("stay.checked_out", 0, 5, b"GR-00001", value, {k: v for k, v in headers.items() if v})


def service(store=None, ledger=None, record=RECORD, decode_error=None):
    def deserialize(value, topic):
        if decode_error:
            raise decode_error
        return dict(record)

    return PostingService(store or FakeStore(), ledger or FakeLedger(), deserialize, FakeDeadLetters())


def test_a_new_event_is_credited_with_the_stay_key_and_written_with_a_child_span():
    svc = service()
    assert svc.handle(message()) is Outcome.POSTED
    assert svc.ledger.calls == [("BR-0001:1", "GR-00001", "BR-0001", 4_500)]
    [(event_id, entry_id, context)] = svc.store.writes
    assert (event_id, entry_id) == (RECORD["event_id"], "L-0000042")
    assert trace.trace_id(context["traceparent"]) == trace.trace_id(TP) and context["traceparent"] != TP
    assert 'posting_events_total{outcome="posted"} 1.0' in svc.metrics.render().decode()


def test_an_already_posted_event_is_a_duplicate_and_the_ledger_isnt_called():
    svc = service(store=FakeStore(posted=True))
    assert svc.handle(message()) is Outcome.DUPLICATE
    assert svc.ledger.calls == [] and svc.store.writes == []


def test_a_race_lost_at_the_insert_is_a_duplicate():
    assert service(store=FakeStore(new=False)).handle(message()) is Outcome.DUPLICATE


@pytest.mark.parametrize(
    ("kwargs", "msg", "error_class"),
    [
        ({"decode_error": ValueError("bad magic byte")}, message(), "schema"),
        ({}, message(value=None), "schema"),
        ({}, message(schema_version="9"), "schema_version"),
        ({"record": {**RECORD, "revision": 2}}, message(), "unsupported_revision"),
        ({"record": {**RECORD, "member_number": "X"}}, message(), "invalid_field"),
        (
            {"ledger": FakeLedger(LedgerPermanent("idempotency_conflict", "L-1"))},
            message(),
            "ledger_idempotency_conflict",
        ),
        ({"ledger": FakeLedger(LedgerPermanent("rejected_422"))}, message(), "ledger_rejected_422"),
    ],
)
def test_what_can_never_post_is_dead_lettered_with_its_class_and_nothing_is_written(kwargs, msg, error_class):
    svc = service(**kwargs)
    assert svc.handle(msg) is Outcome.DEAD_LETTERED
    assert svc.dead_letters.sent == [(5, error_class)]
    assert svc.store.writes == []
    assert f'posting_dlq_messages_total{{error_class="{error_class}"}} 1.0' in svc.metrics.render().decode()


def test_a_transient_ledger_failure_propagates_so_the_consumer_retries():
    svc = service(ledger=FakeLedger(LedgerTransient("unavailable_503")))
    with pytest.raises(LedgerTransient):
        svc.handle(message())
    assert svc.store.writes == [] and svc.dead_letters.sent == []


def test_a_message_without_a_traceparent_starts_a_new_trace():
    svc = service()
    svc.handle(message(traceparent=None))
    assert trace.is_valid(svc.store.writes[0][2]["traceparent"])


def test_the_outbox_payload_has_its_own_fixed_id_and_the_source_event():
    event = validate(RECORD, {"schema_version": "1"})
    a, b = outbox_payload(event, "L-1"), outbox_payload(event, "L-1")
    assert a["event_id"] != b["event_id"]  # a new message ID each time it's built, kept once stored
    assert (a["source_event_id"], a["stay_points"], a["credited_points"]) == (RECORD["event_id"], 4_500, 4_500)
    assert (
        outbox_payload(event, "L-1", now=datetime(2026, 11, 17, tzinfo=UTC))["posted_at"] == 1_794_873_600_000
    )  # 2026-11-17T00:00Z in ms


# ---------- the producer ----------


class FakeProducer:
    def __init__(self, undelivered=0):
        self.sent, self.undelivered = [], undelivered

    def produce(self, topic, key, value, headers):
        self.sent.append((topic, key, value, dict(headers)))

    def flush(self, timeout):
        return self.undelivered


def test_the_producer_keys_by_member_and_sets_the_headers():
    fake = FakeProducer()
    producer = CheckoutProducer(fake, None, "stay.checked_out", serialize=lambda record, ctx: b"avro-bytes")
    sent = producer.send(RECORD)
    topic, key, value, headers = fake.sent[0]
    assert (topic, key, value) == ("stay.checked_out", b"GR-00001", b"avro-bytes")
    assert headers["event_id"] == RECORD["event_id"] == sent.event_id
    assert headers["schema_version"] == "1" and headers["correlation_id"] == RECORD["correlation_id"]
    assert headers["traceparent"] == sent.traceparent and trace.is_valid(sent.traceparent)
    assert producer.send(RECORD, traceparent=TP).traceparent == TP  # an existing trace can be continued


def test_the_producer_reports_undelivered_events_and_needs_a_registry_or_serializer():
    producer = CheckoutProducer(FakeProducer(undelivered=1), None, serialize=lambda record, ctx: b"x")
    with pytest.raises(RuntimeError, match="not delivered"):
        producer.send(RECORD)
    with pytest.raises(ValueError):
        CheckoutProducer(FakeProducer(), None)


def test_synthetic_events_are_valid_and_repeatable():
    events = synthetic_events(25, seed=7)
    assert [e["stay_id"] for e in events] == [e["stay_id"] for e in synthetic_events(25, seed=7)]
    for event in events:
        assert validate(event, {"schema_version": "1"}).revision == 1
