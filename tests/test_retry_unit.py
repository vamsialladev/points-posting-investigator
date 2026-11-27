"""The retry worker's rules and loop, offline, with fakes (ADR-0016). Real-stack behaviour: test_parking_kafka.py."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import pytest

from app.pipeline.events import LatestPosting
from app.pipeline.ledger_client import Credited, LedgerPermanent, LedgerTransient
from app.pipeline.posting import DeadLetterFailure
from app.pipeline.producer import build_event
from app.pipeline.retry import (
    FailureKind,
    ParkedRow,
    ParkedStats,
    RetryConfig,
    RetryCrash,
    RetryWorker,
    parked_failure_outcome,
)

CFG = RetryConfig(worker_id="w1", max_attempts=5, backoff_base=1.0, backoff_cap=60.0)
TP = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
RECORD = build_event(
    member_number="GR-00001",
    stay_id="BR-0001",
    check_in=date(2026, 11, 14),
    nights=2,
    room_rate_cents=20_000,
    occurred_at=datetime(2026, 11, 17, tzinfo=UTC),
)


# ---------- outcomes ----------


def test_a_transient_failure_counts_as_transient_and_never_dead_letters():
    for transient in (0, 5, 500):
        status, attempts, transient_after, step = parked_failure_outcome(2, transient, FailureKind.TRANSIENT, CFG)
        assert (status, attempts, transient_after, step) == ("pending", 2, transient + 1, transient + 1)


def test_a_permanent_failure_counts_and_dead_letters_at_the_maximum():
    assert parked_failure_outcome(0, 3, FailureKind.PERMANENT, CFG)[:3] == ("pending", 1, 3)
    assert parked_failure_outcome(3, 0, FailureKind.PERMANENT, CFG)[:3] == ("pending", 4, 0)
    assert parked_failure_outcome(4, 0, FailureKind.PERMANENT, CFG)[:3] == ("dead", 5, 0)


def test_a_conflict_dead_letters_at_once():
    assert parked_failure_outcome(0, 0, FailureKind.CONFLICT, CFG)[:2] == ("dead", 1)


def test_config_validates():
    with pytest.raises(ValueError):
        RetryConfig(worker_id="")
    with pytest.raises(ValueError):
        RetryConfig(worker_id="w", max_attempts=0)


# ---------- the loop, with fakes ----------


def parked(n=1, attempts=0, transient=0, record=RECORD):
    return ParkedRow(
        id=n,
        event_id=record["event_id"],
        member_number=record["member_number"],
        raw_key=b"GR-00001",
        raw_value=b"avro",
        raw_headers={"event_id": record["event_id"], "schema_version": "1", "traceparent": TP},
        source_topic="stay.checked_out",
        source_partition=0,
        source_offset=10 + n,
        attempts=attempts,
        transient_failures=transient,
        first_failed_at=datetime(2026, 11, 26, tzinfo=UTC),
    )


@dataclass
class FakeParked:
    rows: list
    marks: list = field(default_factory=list)

    def claim(self, worker_id, limit, lease_seconds):
        taken, self.rows = self.rows[:limit], self.rows[limit:]
        return taken

    def mark_failed(self, worker_id, row, status, attempts, transient, error_class, detail, delay):
        self.marks.append((row.id, status, attempts, transient, error_class))
        return 1

    def mark_done(self, worker_id, row):
        self.marks.append((row.id, "done", row.attempts, row.transient_failures, None))
        return 1

    def stats(self):
        return ParkedStats(open=len(self.rows), dead=0, oldest_open_age_seconds=0.0)


@dataclass
class FakePostings:
    posted: bool = False
    latest: LatestPosting | None = None
    writes: list = field(default_factory=list)
    skips: list = field(default_factory=list)

    def already_posted(self, event):
        return self.posted

    def latest_posting(self, stay_id):
        return self.latest

    def record_skipped(self, event, plan):
        self.skips.append((event.event_id, plan.latest_revision))
        return True

    def write(self, event, entry_id, trace_context, fault=None, parked=None, credited=None):
        self.writes.append((event.event_id, entry_id, parked, credited))
        return True


@dataclass
class FakeLedger:
    result: object = field(default_factory=lambda: Credited("L-0000009", False))
    calls: list = field(default_factory=list)

    def credit(self, *args):
        self.calls.append(args)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@dataclass
class FakeDeadLetters:
    fail: bool = False
    sent: list = field(default_factory=list)

    def publish(self, message, error_class, detail, attempts=1, first_failed_at=None):
        if self.fail:
            raise DeadLetterFailure("down")
        self.sent.append((message.value, error_class, attempts, first_failed_at))


def worker(rows, ledger=None, postings=None, dead=None, fault=None, record=RECORD):
    return RetryWorker(
        FakeParked(rows),
        postings or FakePostings(),
        ledger or FakeLedger(),
        lambda value, topic: dict(record),
        dead or FakeDeadLetters(),
        CFG,
        fault=fault,
    )


def test_a_success_writes_the_posting_and_marks_the_parked_event_done_in_one_call():
    w = worker([parked()])
    result = w.run_once()
    assert (result.claimed, result.posted) == (1, 1)
    [(event_id, entry_id, parked_arg, credited)] = w.postings.writes
    assert (event_id, entry_id, credited) == (RECORD["event_id"], "L-0000009", 2_000)
    assert parked_arg == ("w1", 1)  # the store marks it done inside the posting transaction
    assert w.parked.marks == []


# ---------- corrections (RFC-0001 D10) ----------

CORRECTION = {**RECORD, "revision": 2, "room_rate_cents": 25_000}  # 2,500 points; revision 1 earned 2,000


def test_a_parked_correction_credits_the_difference():
    w = worker([parked(record=CORRECTION)], postings=FakePostings(latest=LatestPosting(1, 2_000)), record=CORRECTION)
    assert w.run_once().posted == 1
    assert w.ledger.calls == [("BR-0001:2", "GR-00001", "BR-0001", 500, CORRECTION["correlation_id"])]
    assert w.postings.writes[0][3] == 500


def test_a_parked_stale_revision_is_recorded_and_marked_done_without_a_credit():
    w = worker([parked(record=CORRECTION)], postings=FakePostings(latest=LatestPosting(2, 2_500)), record=CORRECTION)
    assert w.run_once().posted == 0
    assert w.postings.skips == [(CORRECTION["event_id"], 2)]
    assert w.parked.marks == [(1, "done", 0, 0, None)]
    assert w.ledger.calls == [] and w.postings.writes == []


def test_a_correction_whose_original_never_posts_is_dead_lettered_at_the_maximum():
    w = worker([parked(attempts=3, record=CORRECTION)], postings=FakePostings(latest=None), record=CORRECTION)
    w.run_once()
    assert w.parked.marks == [(1, "pending", 4, 0, "original_missing")]
    w = worker([parked(attempts=4, record=CORRECTION)], postings=FakePostings(latest=None), record=CORRECTION)
    w.run_once()
    assert w.parked.marks == [(1, "dead", 5, 0, "original_missing")]
    assert [sent[1:3] for sent in w.dead_letters.sent] == [("original_missing", 5)]
    assert w.ledger.calls == []


def test_an_event_posted_meanwhile_is_just_marked_done():
    w = worker([parked()], postings=FakePostings(posted=True))
    assert w.run_once().posted == 0
    assert w.parked.marks == [(1, "done", 0, 0, None)]


def test_a_transient_failure_is_parked_again_with_its_count_up():
    w = worker([parked(transient=2)], ledger=FakeLedger(LedgerTransient("unavailable_503")))
    w.run_once()
    assert w.parked.marks == [(1, "pending", 0, 3, "ledger_unavailable_503")]


def test_a_permanent_failure_below_the_maximum_is_parked_again():
    w = worker([parked(attempts=2)], ledger=FakeLedger(LedgerPermanent("rejected_422")))
    w.run_once()
    assert w.parked.marks == [(1, "pending", 3, 0, "ledger_rejected_422")]
    assert w.dead_letters.sent == []


def test_at_the_maximum_the_original_bytes_go_to_the_dlq_first_then_it_is_marked_dead():
    w = worker([parked(attempts=4)], ledger=FakeLedger(LedgerPermanent("rejected_422")))
    result = w.run_once()
    assert w.dead_letters.sent == [(b"avro", "ledger_rejected_422", 5, "2026-11-26T00:00:00+00:00")]
    assert w.parked.marks == [(1, "dead", 5, 0, "ledger_rejected_422")]
    assert result.dead == 1


def test_a_conflict_is_dead_lettered_at_once():
    w = worker([parked()], ledger=FakeLedger(LedgerPermanent("idempotency_conflict", "L-1")))
    w.run_once()
    assert w.parked.marks == [(1, "dead", 1, 0, "ledger_idempotency_conflict")]


def test_if_the_dlq_is_down_nothing_is_marked_and_the_lease_will_run_out():
    w = worker(
        [parked(attempts=4)], ledger=FakeLedger(LedgerPermanent("rejected_422")), dead=FakeDeadLetters(fail=True)
    )
    w.run_once()
    assert w.parked.marks == []


def test_an_undecodable_parked_event_is_dead_lettered():
    w = RetryWorker(
        FakeParked([parked()]),
        FakePostings(),
        FakeLedger(),
        lambda value, topic: (_ for _ in ()).throw(ValueError("bad bytes")),
        FakeDeadLetters(),
        CFG,
    )
    w.run_once()
    assert w.parked.marks[0][1] == "dead" and w.dead_letters.sent[0][1] == "schema"


def test_a_crash_after_the_credit_marks_nothing():
    def crash(point):
        if point == "after_ledger_credit":
            raise RetryCrash(point)

    w = worker([parked()], fault=crash)
    with pytest.raises(RetryCrash):
        w.run_once()
    assert w.postings.writes == [] and w.parked.marks == []


def test_metrics_render_the_parked_stats():
    w = worker([])
    w.run_once()
    text = w.metrics.render().decode()
    assert "posting_parked_open 0.0" in text and "posting_parked_oldest_age_seconds 0.0" in text
