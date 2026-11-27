"""PostingService's decisions, offline, with fakes for the store, the ledger and the dead-letter publisher.

The store's SQL (one transaction, ON CONFLICT) and everything against real Kafka and Postgres is tested in
test_posting_kafka.py. Here: what the service decides for each kind of message, and what it passes on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import pytest

from app.pipeline import trace
from app.pipeline.events import LatestPosting, validate
from app.pipeline.ledger_client import Credited, LedgerPermanent, LedgerTransient
from app.pipeline.posting import IncomingMessage, Outcome, PostingService, outbox_payload
from app.pipeline.producer import CheckoutProducer, DeliveryFailed, build_event, synthetic_events

TP = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"


@dataclass
class FakeStore:
    posted: bool = False
    new: bool = True
    parked_already: bool = False
    member_parked: bool = False
    latest: LatestPosting | None = None
    skipped_new: bool = True
    writes: list = field(default_factory=list)
    parks: list = field(default_factory=list)
    skips: list = field(default_factory=list)
    credited: list = field(default_factory=list)

    def already_posted(self, event):
        return self.posted

    def already_parked(self, event_id):
        return self.parked_already

    def member_has_parked(self, member_number):
        return self.member_parked

    def park(self, message, event, reason, delay):
        self.parks.append((event.event_id, reason.kind, reason.error_class))
        return True

    def latest_posting(self, stay_id):
        return self.latest

    def record_skipped(self, event, plan):
        self.skips.append((event.event_id, event.revision, plan.latest_revision))
        return self.skipped_new

    def write(self, event, entry_id, trace_context, fault=None, parked=None, credited=None):
        self.writes.append((event.event_id, entry_id, dict(trace_context)))
        self.credited.append(credited)
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

    def publish(self, message, error_class, detail, attempts=1, first_failed_at=None):
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
        ({"record": {**RECORD, "revision": 0}}, message(), "invalid_field"),
        ({"record": {**RECORD, "member_number": "X"}}, message(), "invalid_field"),
        (
            {"ledger": FakeLedger(LedgerPermanent("idempotency_conflict", "L-1"))},
            message(),
            "ledger_idempotency_conflict",
        ),
    ],
)
def test_what_can_never_post_is_dead_lettered_with_its_class_and_nothing_is_written(kwargs, msg, error_class):
    svc = service(**kwargs)
    assert svc.handle(msg) is Outcome.DEAD_LETTERED
    assert svc.dead_letters.sent == [(5, error_class)]
    assert svc.store.writes == []
    assert f'posting_dlq_messages_total{{error_class="{error_class}"}} 1.0' in svc.metrics.render().decode()


@pytest.mark.parametrize(
    ("failure", "kind", "error_class"),
    [
        (LedgerTransient("unavailable_503"), "transient", "ledger_unavailable_503"),
        (LedgerTransient("unauthorized"), "transient", "ledger_unauthorized"),
        (LedgerPermanent("rejected_422"), "permanent", "ledger_rejected_422"),  # counted; dead after 5 (ADR-0016)
    ],
)
def test_a_ledger_failure_parks_the_event_instead_of_blocking_the_partition(failure, kind, error_class):
    svc = service(ledger=FakeLedger(failure))
    assert svc.handle(message()) is Outcome.PARKED
    assert svc.store.parks == [(RECORD["event_id"], kind, error_class)]
    assert svc.store.writes == [] and svc.dead_letters.sent == []


def test_an_event_behind_a_parked_one_parks_too_without_calling_the_ledger():
    # Per-member order: event 2 must not overtake event 1 while event 1 waits for a retry.
    svc = service(store=FakeStore(member_parked=True))
    assert svc.handle(message()) is Outcome.PARKED
    assert svc.store.parks == [(RECORD["event_id"], "behind", None)]
    assert svc.ledger.calls == []


# ---------- corrections (RFC-0001 D10) ----------

CORRECTION = {**RECORD, "revision": 2, "room_rate_cents": 50_000}  # 5,000 points; revision 1 earned 4,500


def test_a_correction_credits_the_difference_under_its_own_key_and_posts_it():
    svc = service(store=FakeStore(latest=LatestPosting(1, 4_500)), record=CORRECTION)
    assert svc.handle(message()) is Outcome.POSTED
    assert svc.ledger.calls == [("BR-0001:2", "GR-00001", "BR-0001", 500)]
    assert svc.store.credited == [500]


def test_a_correction_down_credits_a_negative_difference():
    svc = service(store=FakeStore(latest=LatestPosting(1, 4_500)), record={**CORRECTION, "room_rate_cents": 30_000})
    assert svc.handle(message()) is Outcome.POSTED
    assert svc.ledger.calls[0][3] == -1_500 and svc.store.credited == [-1_500]


def test_a_stale_revision_is_recorded_and_skipped_without_a_credit():
    svc = service(store=FakeStore(latest=LatestPosting(3, 6_000)), record=CORRECTION)
    assert svc.handle(message()) is Outcome.SKIPPED
    assert svc.store.skips == [(RECORD["event_id"], 2, 3)]
    assert svc.ledger.calls == [] and svc.store.writes == [] and svc.dead_letters.sent == []
    assert 'posting_events_total{outcome="skipped"} 1.0' in svc.metrics.render().decode()


def test_a_stale_revision_seen_again_is_a_duplicate():
    svc = service(store=FakeStore(latest=LatestPosting(3, 6_000), skipped_new=False), record=CORRECTION)
    assert svc.handle(message()) is Outcome.DUPLICATE


def test_a_correction_before_its_original_is_parked_as_original_missing():
    svc = service(store=FakeStore(latest=None), record=CORRECTION)
    assert svc.handle(message()) is Outcome.PARKED
    assert svc.store.parks == [(RECORD["event_id"], "permanent", "original_missing")]  # counted: dead at the max
    assert svc.ledger.calls == []


def test_a_redelivered_parked_event_is_a_duplicate():
    svc = service(store=FakeStore(parked_already=True))
    assert svc.handle(message()) is Outcome.DUPLICATE
    assert svc.store.parks == [] and svc.ledger.calls == []


def test_a_message_without_a_traceparent_starts_a_new_trace():
    svc = service()
    svc.handle(message(traceparent=None))
    assert trace.is_valid(svc.store.writes[0][2]["traceparent"])


def test_the_outbox_payload_has_its_own_fixed_id_and_the_source_event():
    event = validate(RECORD, {"schema_version": "1"})
    a, b = outbox_payload(event, "L-1"), outbox_payload(event, "L-1")
    assert a["event_id"] != b["event_id"]  # a new message ID each time it's built, kept once stored
    assert (a["source_event_id"], a["stay_points"], a["credited_points"]) == (RECORD["event_id"], 4_500, 4_500)
    assert outbox_payload(event, "L-1", credited=-200)["credited_points"] == -200  # a correction's difference
    assert (
        outbox_payload(event, "L-1", now=datetime(2026, 11, 17, tzinfo=UTC))["posted_at"] == 1_794_873_600_000
    )  # 2026-11-17T00:00Z in ms


# ---------- the producer ----------


class FakeProducer:
    def __init__(self, undelivered=0):
        self.sent, self.undelivered, self.callbacks = [], undelivered, []

    def produce(self, topic, key, value, headers, on_delivery):
        self.sent.append((topic, key, value, dict(headers)))
        self.callbacks.append(on_delivery)

    def flush(self, timeout):
        if not self.undelivered:  # delivered: every message gets its report
            for callback in self.callbacks:
                callback(None, None)
        self.callbacks = []
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
    with pytest.raises(DeliveryFailed, match="not delivered"):
        producer.send(RECORD)
    with pytest.raises(ValueError):
        CheckoutProducer(FakeProducer(), None)


def test_synthetic_events_are_valid_and_repeatable():
    events = synthetic_events(25, seed=7)
    assert [e["stay_id"] for e in events] == [e["stay_id"] for e in synthetic_events(25, seed=7)]
    for event in events:
        assert validate(event, {"schema_version": "1"}).revision == 1
