"""Posting service rules, ledger client and consumer loop, offline (ADR-0015). Real-stack: test_posting_kafka.py."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import httpx
import pytest
from confluent_kafka import KafkaError, KafkaException

from app.pipeline import trace
from app.pipeline.events import (
    CreditKind,
    CreditPlan,
    InvalidEvent,
    LatestPosting,
    ledger_key,
    plan_credit,
    points_for,
    validate,
)
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
        ({"revision": 0}, {}, "invalid_field"),  # 1 is the original; corrections are 2 and up (D10)
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


# ---------- corrections (RFC-0001 D10) ----------


def event_at(revision, room_rate_cents=45_000):
    rec = record(revision=revision, room_rate_cents=room_rate_cents)
    return validate(rec, headers(rec))


def test_a_correction_is_valid_and_has_its_own_ledger_key():
    assert ledger_key(event_at(3)) == "BR-0001:3"


@pytest.mark.parametrize(
    ("revision", "rate", "latest", "expected"),
    [
        (1, 45_000, None, CreditPlan(CreditKind.CREDIT, 4_500)),  # an original: the whole stay
        (2, 50_000, LatestPosting(1, 4_500), CreditPlan(CreditKind.CREDIT, 500, 1)),  # rate up: +500
        (2, 30_000, LatestPosting(1, 4_500), CreditPlan(CreditKind.CREDIT, -1_500, 1)),  # rate down: negative
        (2, 45_000, LatestPosting(1, 4_500), CreditPlan(CreditKind.CREDIT, 0, 1)),  # same points: a zero credit
        (4, 60_000, LatestPosting(2, 5_000), CreditPlan(CreditKind.CREDIT, 1_000, 2)),  # a gap: from the latest
        (2, 50_000, LatestPosting(3, 6_000), CreditPlan(CreditKind.STALE, 0, 3)),  # older than the latest
        (3, 50_000, LatestPosting(3, 6_000), CreditPlan(CreditKind.STALE, 0, 3)),  # equal (another event ID)
        (1, 45_000, LatestPosting(2, 5_000), CreditPlan(CreditKind.STALE, 0, 2)),  # a late original
        (2, 50_000, None, CreditPlan(CreditKind.ORIGINAL_MISSING)),  # a correction before its original
    ],
)
def test_the_correction_rule(revision, rate, latest, expected):
    assert plan_credit(event_at(revision, rate), latest) == expected


def test_corrections_add_up_to_the_latest_revision_whatever_the_gaps():
    """Credits over revisions 1, 2 and 4 (3 never arrives) sum to what revision 4 earns: nothing lost, nothing twice."""
    latest, total = None, 0
    for revision, rate in [(1, 45_000), (2, 52_000), (4, 39_900)]:
        event = event_at(revision, rate)
        plan = plan_credit(event, latest)
        total += plan.credited_points
        latest = LatestPosting(revision, points_for(event))
    assert total == points_for(event_at(4, 39_900)) == 3_990
    assert plan_credit(event_at(3, 99_000), latest).kind == CreditKind.STALE  # revision 3 arriving now is skipped


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
def test_a_retryable_failure_seeks_back_and_commits_nothing(failure, caplog):
    posting, _, consumer, sleeps = loop(failure)
    with caplog.at_level("WARNING", logger="posting"):
        assert posting.run_once() is Outcome.RETRY
    assert consumer.commits == [] and consumer.seeks == [("stay.checked_out", 1, 7)]
    assert sleeps and sleeps[0] > 0
    # The retry leaves a log line naming the failure's type and the message, never the failure's text (S07).
    (line,) = [record.getMessage() for record in caplog.records]
    assert line == f"retrying stay.checked_out/1@7 in place after {type(failure).__name__} (attempt 1)"


def test_a_rebalance_leaves_one_line_naming_the_partitions(caplog):
    from types import SimpleNamespace

    from app.pipeline.posting import log_rebalance

    partitions = [SimpleNamespace(topic="stay.checked_out", partition=n) for n in (2, 0)]
    with caplog.at_level("INFO", logger="posting"):
        log_rebalance("assigned", partitions)
        log_rebalance("revoked", [])
    assert [record.getMessage() for record in caplog.records] == [
        "partitions assigned: stay.checked_out/0, stay.checked_out/2",
        "partitions revoked: none",
    ]


def test_the_consumer_subscribes_with_callbacks_that_only_log(monkeypatch):
    """The callbacks must not take over the assignment: they never call assign() or unassign()."""
    from app.pipeline import posting as module

    calls: dict[str, object] = {}

    class Recorder:
        def __init__(self, config):
            calls["config"] = config

        def subscribe(self, topics, on_assign=None, on_revoke=None):
            calls.update(topics=topics, on_assign=on_assign, on_revoke=on_revoke)

        def __getattr__(self, name):  # assign, unassign, anything else: the callbacks must not touch the consumer
            raise AssertionError(f"a rebalance callback called consumer.{name}")

    monkeypatch.setattr(module, "Consumer", Recorder)
    consumer = module.make_consumer("127.0.0.1:9092", "posting-service", ["stay.checked_out"])
    assert calls["topics"] == ["stay.checked_out"] and calls["config"]["enable.auto.commit"] is False
    calls["on_assign"](consumer, [])  # type: ignore[operator]
    calls["on_revoke"](consumer, [])  # type: ignore[operator]


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


def test_a_failed_offset_commit_is_a_warning_and_the_loop_goes_on(caplog):
    """The database transaction already committed, so the work is done: a commit failure (here the group coordinator
    is unavailable, as seen in the M2 PR-B2b full run) must not crash the cycle or retry the message. Offsets are
    cumulative per partition, so the next successful commit covers this one; if none comes (a crash or rebalance), the
    message is redelivered and recognised as a duplicate."""
    from app.pipeline.posting import PostingMetrics

    posting, service, consumer, _ = loop(Outcome.POSTED)
    service.metrics = PostingMetrics()

    def refuse(message, asynchronous):
        raise KafkaException(KafkaError(KafkaError._WAIT_COORD))

    consumer.commit = refuse
    assert posting.run_once() is Outcome.POSTED
    assert consumer.seeks == []  # not retried: it was posted
    assert posting.consecutive_failures == 0
    assert "offset commit failed" in caplog.text
    assert 'posting_offset_commit_failures_total{error="_WAIT_COORD"} 1.0' in service.metrics.render().decode()


def test_nothing_to_poll():
    posting, _, consumer, _ = loop(Outcome.POSTED)
    consumer.messages = []
    assert posting.run_once() is None


def test_trace_helpers_give_the_posting_span_a_child_of_the_producer():
    stored = {"traceparent": trace.child(TP)}
    assert trace.trace_id(stored["traceparent"]) == trace.trace_id(TP)
