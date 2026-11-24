"""Posting service rules, ledger client and consumer loop, offline (ADR-0015). Real-stack: test_posting_kafka.py."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import httpx
import pytest
from confluent_kafka import KafkaError

from app.pipeline import trace
from app.pipeline.events import InvalidEvent, ledger_key, points_for, validate
from app.pipeline.ledger_client import Credited, LedgerClient, LedgerPermanent, LedgerTransient
from app.pipeline.posting import (
    DatabaseFailure,
    DeadLetterFailure,
    DeadLetterPublisher,
    IncomingMessage,
    Outcome,
    PostingConsumer,
    PostingCrash,
)
from app.pipeline.producer import build_event

TP = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"


def record(**changes):
    base = build_event(
        member_number="GR-00001",
        stay_id="BR-0001",
        check_in=date(2026, 11, 14),
        nights=3,
        room_rate_cents=45_000,
        taxes_cents=5_400,
        fees_cents=3_000,
        occurred_at=datetime(2026, 11, 17, 12, tzinfo=UTC),
    )
    return {**base, **changes}


def headers(rec, **changes):
    return {"event_id": rec["event_id"], "schema_version": "1", "correlation_id": rec["correlation_id"], **changes}


# ---------- validation and points ----------


def test_a_valid_event():
    rec = record()
    event = validate(rec, headers(rec))
    assert (event.member_number, event.stay_id, event.revision, event.nights) == ("GR-00001", "BR-0001", 1, 3)
    assert uuid.UUID(event.event_id)


@pytest.mark.parametrize(
    ("changes", "header_changes", "code"),
    [
        ({}, {"schema_version": "2"}, "schema_version"),
        ({}, {"schema_version": None}, "schema_version"),
        ({}, {"event_id": str(uuid.UUID(int=1))}, "invalid_field"),  # header and record disagree
        ({"event_id": "not-a-uuid"}, {"event_id": "not-a-uuid"}, "invalid_field"),
        ({"tenant": "other"}, {}, "invalid_field"),
        ({"property": "city-hotel"}, {}, "invalid_field"),
        ({"stay_id": "ML-0001"}, {}, "invalid_field"),  # Beach Resort stays are BR-
        ({"member_number": "GR-1"}, {}, "invalid_field"),
        ({"nights": 2}, {}, "invalid_field"),  # check_in..check_out is 3 nights
        ({"room_rate_cents": -1}, {}, "invalid_field"),
        ({"currency": "EUR"}, {}, "invalid_field"),
        ({"revision": 2}, {}, "unsupported_revision"),  # corrections come in PR-C
    ],
)
def test_invalid_events_are_refused_with_a_reason(changes, header_changes, code):
    rec = record(**changes)
    hdrs = {k: v for k, v in headers(rec, **header_changes).items() if v is not None}
    with pytest.raises(InvalidEvent) as error:
        validate(rec, hdrs)
    assert error.value.code == code


def test_only_the_room_rate_earns_ten_points_a_dollar_rounded_down():
    rec = record(room_rate_cents=45_009, taxes_cents=99_999, fees_cents=99_999)
    assert points_for(validate(rec, headers(rec))) == 4_500


def test_the_ledger_key_is_the_business_key():
    rec = record()
    assert ledger_key(validate(rec, headers(rec))) == "BR-0001:1"


def test_build_event_makes_a_valid_event_each_time():
    a, b = record(), record()
    assert a["event_id"] != b["event_id"]
    assert a["check_out"] == date(2026, 11, 17) and a["property"] == "beach-resort"
    lodge = build_event(
        member_number="GR-00002", stay_id="ML-0002", check_in=date(2026, 11, 1), nights=1, room_rate_cents=1
    )
    assert validate(lodge, headers(lodge)).stay_id == "ML-0002"


# ---------- the ledger client ----------


def client(handler, **kwargs):
    sleeps: list[float] = []
    ledger = LedgerClient(
        "http://ledger.test",
        "fake-ledger-token-1",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        **kwargs,
    )
    return ledger, sleeps


ENTRY = {
    "entry_id": "L-0000007",
    "idempotency_key": "BR-0001:1",
    "member_number": "GR-00001",
    "stay_id": "BR-0001",
    "points": 4500,
    "correlation_id": "c",
    "created_at": "2026-11-17T12:00:00+00:00",
}


def credit(ledger):
    return ledger.credit("BR-0001:1", "GR-00001", "BR-0001", 4500, "c")


@pytest.mark.parametrize(("status", "replayed"), [(201, False), (200, True)])
def test_a_credit_or_a_replay(status, replayed):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, json={**ENTRY, "replayed": replayed})

    ledger, _ = client(handler)
    assert credit(ledger) == Credited("L-0000007", replayed)
    assert seen[0].headers["Idempotency-Key"] == "BR-0001:1"
    assert seen[0].headers["Authorization"] == "Bearer fake-ledger-token-1"


@pytest.mark.parametrize(
    ("status", "body", "kind", "reason"),
    [
        (409, {"error": "idempotency_conflict", "entry_id": "L-0000001"}, LedgerPermanent, "idempotency_conflict"),
        (422, {"detail": []}, LedgerPermanent, "rejected_422"),
        (400, {}, LedgerPermanent, "rejected_400"),
        (401, {"detail": {"error": "token_expired"}}, LedgerTransient, "unauthorized"),
        (429, {}, LedgerTransient, "rate_limited"),
        (503, {}, LedgerTransient, "unavailable_503"),
    ],
)
def test_ledger_replies_are_classified(status, body, kind, reason):
    ledger, _ = client(lambda request: httpx.Response(status, json=body, headers={"Retry-After": "3"}))
    with pytest.raises(kind) as error:
        credit(ledger)
    assert error.value.reason == reason
    if status == 429:
        assert error.value.retry_after == 3.0


def test_a_timeout_is_resolved_by_status_lookups_before_any_retry():
    calls = {"post": 0, "get": 0}

    def handler(request):
        if request.method == "POST":
            calls["post"] += 1
            raise httpx.ReadTimeout("simulated", request=request)
        calls["get"] += 1
        # The credit landed after all: the second lookup finds it (Stage 9: one "not found" is not proof).
        return httpx.Response(200, json={**ENTRY, "replayed": False}) if calls["get"] == 2 else httpx.Response(404)

    ledger, sleeps = client(handler, settle_seconds=0.25)
    assert credit(ledger) == Credited("L-0000007", True)
    assert calls == {"post": 1, "get": 2} and sleeps == [0.25]


def test_a_timeout_with_no_credit_found_is_transient():
    def handler(request):
        if request.method == "POST":
            raise httpx.ReadTimeout("simulated", request=request)
        return httpx.Response(404)

    ledger, sleeps = client(handler, lookups=2, settle_seconds=0.1)
    with pytest.raises(LedgerTransient) as error:
        credit(ledger)
    assert error.value.reason == "timeout_not_found" and sleeps == [0.1, 0.1]


def test_a_found_credit_with_other_points_is_a_conflict_not_a_success():
    def handler(request):
        if request.method == "POST":
            raise httpx.ReadTimeout("simulated", request=request)
        return httpx.Response(200, json={**ENTRY, "points": 1, "replayed": False})

    ledger, _ = client(handler)
    with pytest.raises(LedgerPermanent) as error:
        credit(ledger)
    assert error.value.reason == "idempotency_conflict"


def test_a_connection_error_is_transient():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    ledger, _ = client(handler)
    with pytest.raises(LedgerTransient) as error:
        credit(ledger)
    assert error.value.reason == "unreachable"


# ---------- dead letters ----------


class FakeProducer:
    def __init__(self, error=None):
        self.error, self.sent = error, []

    def produce(self, topic, key, value, headers, on_delivery):
        self.sent.append((topic, key, value, dict(headers)))
        self._callback = on_delivery

    def flush(self, timeout):
        self._callback(self.error, None)
        return 0


MESSAGE = IncomingMessage(
    "stay.checked_out", 2, 41, b"GR-00001", b"\x00raw", {"event_id": "e1", "correlation_id": "c1"}
)


def test_a_dead_letter_keeps_the_original_bytes_and_says_why():
    producer = FakeProducer()
    DeadLetterPublisher(producer, "stay.checked_out.dlq").publish(MESSAGE, "schema", "bad magic byte", attempts=1)
    topic, key, value, hdrs = producer.sent[0]
    assert (topic, key, value) == ("stay.checked_out.dlq", b"GR-00001", b"\x00raw")
    assert hdrs["event_id"] == "e1" and hdrs["correlation_id"] == "c1"
    assert hdrs["error_class"] == "schema" and hdrs["error_detail"] == "bad magic byte"
    assert (hdrs["attempt"], hdrs["original_topic"], hdrs["original_partition"], hdrs["original_offset"]) == (
        "1",
        "stay.checked_out",
        "2",
        "41",
    )
    assert hdrs["first_failed_at"] and hdrs["last_failed_at"]


def test_a_dead_letter_that_isnt_delivered_raises():
    with pytest.raises(DeadLetterFailure):
        DeadLetterPublisher(FakeProducer(KafkaError(KafkaError._MSG_TIMED_OUT)), "dlq").publish(MESSAGE, "schema", "x")


# ---------- the consumer loop ----------


@dataclass
class FakeKafkaMessage:
    def error(self):
        return None

    def topic(self):
        return "stay.checked_out"

    def partition(self):
        return 1

    def offset(self):
        return 7

    def key(self):
        return b"GR-00001"

    def value(self):
        return b"v"

    def headers(self):
        return [("traceparent", TP.encode())]


@dataclass
class FakeConsumer:
    messages: list = field(default_factory=lambda: [FakeKafkaMessage()])
    commits: list = field(default_factory=list)
    seeks: list = field(default_factory=list)

    def poll(self, timeout):
        return self.messages.pop(0) if self.messages else None

    def commit(self, message, asynchronous):
        assert asynchronous is False  # the offset is committed synchronously, after the database
        self.commits.append(message.offset())

    def seek(self, partition):
        self.seeks.append((partition.topic, partition.partition, partition.offset))


class FakeService:
    def __init__(self, result):
        self.result, self.seen, self.fault = result, [], None

    def handle(self, message):
        self.seen.append(message)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def loop(result, fault=None):
    service, consumer, sleeps = FakeService(result), FakeConsumer(), []
    service.fault = fault
    return PostingConsumer(service, consumer, sleep=sleeps.append, rand=lambda: 1.0), service, consumer, sleeps


@pytest.mark.parametrize("outcome", [Outcome.POSTED, Outcome.DUPLICATE, Outcome.DEAD_LETTERED])
def test_the_offset_is_committed_after_the_service_returns(outcome):
    posting, service, consumer, _ = loop(outcome)
    assert posting.run_once() is outcome
    assert consumer.commits == [7] and consumer.seeks == []
    assert service.seen[0].headers["traceparent"] == TP and service.seen[0].key == b"GR-00001"


@pytest.mark.parametrize(
    "failure", [DatabaseFailure("connection lost"), LedgerTransient("unavailable_503"), DeadLetterFailure("down")]
)
def test_a_retryable_failure_seeks_back_and_commits_nothing(failure):
    posting, _, consumer, sleeps = loop(failure)
    assert posting.run_once() is Outcome.RETRY
    assert consumer.commits == [] and consumer.seeks == [("stay.checked_out", 1, 7)]
    assert sleeps and sleeps[0] > 0


def test_retry_waits_grow_and_reset_after_a_success():
    posting, service, consumer, sleeps = loop(DatabaseFailure("down"))
    consumer.messages = [FakeKafkaMessage() for _ in range(4)]
    for _ in range(3):
        posting.run_once()
    service.result = Outcome.POSTED
    posting.run_once()
    assert sleeps == sorted(sleeps) and len(set(sleeps)) == 3
    assert posting.consecutive_failures == 0


def test_a_crash_after_the_database_commit_leaves_the_offset_uncommitted():
    def crash(point):
        if point == "after_db_commit_before_offset_commit":
            raise PostingCrash(point)

    posting, _, consumer, _ = loop(Outcome.POSTED, fault=crash)
    with pytest.raises(PostingCrash):
        posting.run_once()
    assert consumer.commits == []


def test_nothing_to_poll():
    posting, _, consumer, _ = loop(Outcome.POSTED)
    consumer.messages = []
    assert posting.run_once() is None


def test_trace_helpers_give_the_posting_span_a_child_of_the_producer():
    stored = {"traceparent": trace.child(TP)}
    assert trace.trace_id(stored["traceparent"]) == trace.trace_id(TP)
