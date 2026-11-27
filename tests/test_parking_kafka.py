"""Parking and the retry worker on the real stack: Kafka + Karapace, Postgres, the real ledger app over HTTP (ADR-0016).

Failures are real where the stack can produce them: a stay over the ledger's points limit gets a real 422, and a
ledger at a closed port gives real connection errors. A transient failure for one chosen stay is injected in front
of the real ledger client (`FlakyLedger`). The crash, concurrency, order and poison tests are run 10 times by
scripts\\repeat_tests.ps1 (verification log, M2 PR-B2b).
"""

from __future__ import annotations

import collections
import threading
import uuid

import pytest
from sqlalchemy import select, text

from app.pipeline.posting import DatabaseFailure, Outcome, PostingCrash
from app.pipeline.retry import RetryCrash
from app.pipeline.tables import outbox, posting
from tests.ledger_checks import credit_problems
from tests.pipeline_fixtures import expected_credits, stay
from tests.posting_helpers import (
    FlakyLedger,
    checkout_producer,
    counts,
    drain_parked,
    make_loop,
    make_service,
    make_worker,
    parked_rows,
    read_raw,
    run_until,
)
from tests.relay_helpers import drain, make_relay, open_rows, per_member_order, read_topic

pytestmark = [pytest.mark.postgres, pytest.mark.kafka]


def consumer_for(db, ledger, kafka, registry, scratch, *, wrap=None, fault=None, group=None):
    url, token = ledger
    service = make_service(
        db["posting"], url, token, kafka, registry, scratch["output"], scratch["dlq"], fault=fault, wrap=wrap
    )
    return make_loop(service, kafka, group or "g-" + uuid.uuid4().hex[:6], scratch["input"])


def postings_in_order(engine) -> dict[str, list[str]]:
    """Each member's posted stay IDs, in the order the postings were written."""
    with engine.connect() as conn:
        rows = conn.execute(select(posting.c.member_number, posting.c.stay_id).order_by(posting.c.posted_at)).all()
    order: dict[str, list[str]] = collections.defaultdict(list)
    for member, stay_id in rows:
        order[member].append(stay_id)
    return dict(order)


def test_a_poison_event_is_retried_to_the_maximum_then_dead_lettered_and_nobody_else_waits(
    db, ledger, kafka, registry, scratch
):
    """Outcomes are checked per event, not as a sequence. The two members' events can sit on different partitions,
    and Kafka orders messages within a partition only: the consumer may read the other member's event first. A first
    version asserted the order [PARKED, PARKED, POSTED] and failed once in 10 runs for exactly that reason (M2 PR-B2b
    repeat runs, poison run 8). Per-member order is asserted by the order tests."""
    poison = stay("GR-00001", 1, room_rate_cents=200_000_000)  # 20,000,000 points: over the ledger's limit, a real 422
    later_same_member = stay("GR-00001", 3)
    other_member = stay("GR-00002", 5)
    producer = checkout_producer(kafka, registry, scratch["input"])
    for rec in (poison, later_same_member, other_member):
        producer.send(rec)
    loop = consumer_for(db, ledger, kafka, registry, scratch)
    assert sorted(run_until(loop, 3)) == sorted([Outcome.PARKED, Outcome.PARKED, Outcome.POSTED])
    with db["posting"].connect() as conn:
        posted_before_any_retry = {r.event_id for r in conn.execute(select(posting.c.event_id))}
    assert posted_before_any_retry == {other_member["event_id"]}  # the other member didn't wait
    assert {r["event_id"] for r in parked_rows(db["posting"])} == {poison["event_id"], later_same_member["event_id"]}

    drain_parked(make_worker(db, ledger, kafka, registry, scratch, max_attempts=5), db)
    rows = {r["event_id"]: r for r in parked_rows(db["posting"])}
    dead, behind = rows[poison["event_id"]], rows[later_same_member["event_id"]]
    assert (dead["status"], dead["attempts"], dead["error_class"]) == ("dead", 5, "ledger_rejected_422")
    assert behind["status"] == "done" and behind["done_at"] > dead["dead_at"]  # unblocked once the poison died

    [message] = read_raw(kafka, scratch["dlq"], at_least=1)
    headers = {k: v.decode() for k, v in message.headers()}
    assert message.value() == dead["raw_value"] and message.key() == b"GR-00001"  # the original bytes
    assert (headers["error_class"], headers["attempt"]) == ("ledger_rejected_422", "5")
    assert headers["event_id"] == poison["event_id"] and headers["first_failed_at"] != headers["last_failed_at"]
    assert counts(db["posting"]) == (2, 2)
    with db["ledger"].connect() as conn:
        assert credit_problems(conn, expected_credits(later_same_member, other_member)) == []


def test_per_member_order_holds_while_the_first_event_retries(db, ledger, kafka, registry, scratch):
    mine = [stay("GR-00001", n) for n in (1, 2, 3, 4)]
    theirs = [stay("GR-00002", n) for n in (5, 6)]
    producer = checkout_producer(kafka, registry, scratch["input"])
    for rec in mine[:2] + theirs[:1] + mine[2:] + theirs[1:]:  # interleaved
        producer.send(rec)
    flaky = {mine[0]["stay_id"]: 1}  # the consumer's one try fails; then the worker's first 2 fail too

    loop = consumer_for(db, ledger, kafka, registry, scratch, wrap=lambda c: FlakyLedger(c, flaky))
    outcomes = run_until(loop, 6)
    assert outcomes.count(Outcome.PARKED) == 4 and outcomes.count(Outcome.POSTED) == 2  # mine parked, theirs posted

    worker = make_worker(db, ledger, kafka, registry, scratch, wrap=lambda c: FlakyLedger(c, {mine[0]["stay_id"]: 2}))
    drain_parked(worker, db)
    assert postings_in_order(db["posting"]) == {
        "GR-00002": [r["stay_id"] for r in theirs],
        "GR-00001": [r["stay_id"] for r in mine],
    }
    first = next(r for r in parked_rows(db["posting"]) if r["event_id"] == mine[0]["event_id"])
    assert (first["attempts"], first["transient_failures"]) == (0, 3)  # outages are counted, never toward dead

    relay = make_relay("r1", kafka, registry, db["relay"], scratch["output"])
    drain([relay], lambda: open_rows(db["relay"]) == 0)
    received = read_topic(kafka, registry, scratch["output"], at_least=6)
    order = per_member_order(received)  # stay_points per member, in partition order
    points = {r["stay_id"]: (r["room_rate_cents"] * 10) // 100 for r in mine + theirs}
    assert order["GR-00001"] == [points[r["stay_id"]] for r in mine]
    assert order["GR-00002"] == [points[r["stay_id"]] for r in theirs]


def test_a_crash_after_parking_before_the_offset_commit_redelivers_and_stays_one_parked_row(
    db, ledger, kafka, registry, scratch
):
    rec = stay("GR-00001", 1)
    checkout_producer(kafka, registry, scratch["input"]).send(rec)
    group = "g-" + uuid.uuid4().hex[:6]

    def crash(point: str) -> None:
        if point == "after_db_commit_before_offset_commit":
            raise PostingCrash(point)

    always = lambda c: FlakyLedger(c, {rec["stay_id"]: 1000})  # noqa: E731
    first = consumer_for(db, ledger, kafka, registry, scratch, wrap=always, fault=crash, group=group)
    with pytest.raises(PostingCrash):
        run_until(first, 1)
    first.consumer.close()
    second = consumer_for(db, ledger, kafka, registry, scratch, wrap=always, group=group)
    assert run_until(second, 1) == [Outcome.DUPLICATE]  # recognised as already parked
    assert len(parked_rows(db["posting"])) == 1


def test_a_worker_crash_after_the_credit_is_finished_by_another_worker_with_one_credit(
    db, ledger, kafka, registry, scratch
):
    rec = stay("GR-00001", 1)
    checkout_producer(kafka, registry, scratch["input"]).send(rec)
    loop = consumer_for(db, ledger, kafka, registry, scratch, wrap=lambda c: FlakyLedger(c, {rec["stay_id"]: 1}))
    assert run_until(loop, 1) == [Outcome.PARKED]

    def crash(point: str) -> None:
        if point == "after_ledger_credit":
            raise RetryCrash(point)

    crashed = make_worker(db, ledger, kafka, registry, scratch, worker_id="w-crashed", fault=crash, lease_seconds=1.0)
    with pytest.raises(RetryCrash):
        crashed.run_once()
    survivor = make_worker(db, ledger, kafka, registry, scratch, worker_id="w-survivor", lease_seconds=1.0)
    drain_parked(survivor, db, timeout=30)
    [row] = parked_rows(db["posting"])
    assert (row["status"], row["claimed_by"]) == ("done", "w-survivor")
    assert counts(db["posting"]) == (1, 1)
    with db["ledger"].connect() as conn:
        assert credit_problems(conn, expected_credits(rec)) == []  # the survivor got the same entry back


def test_a_db_failure_inside_the_worker_transaction_writes_nothing_and_is_retried(db, ledger, kafka, registry, scratch):
    rec = stay("GR-00001", 1)
    checkout_producer(kafka, registry, scratch["input"]).send(rec)
    loop = consumer_for(db, ledger, kafka, registry, scratch, wrap=lambda c: FlakyLedger(c, {rec["stay_id"]: 1}))
    assert run_until(loop, 1) == [Outcome.PARKED]
    failed = {"n": 0}

    def fail_once(point: str) -> None:
        if point == "mid_transaction" and failed["n"] == 0:
            failed["n"] += 1
            raise DatabaseFailure("simulated failure inside the worker's posting transaction")

    worker = make_worker(db, ledger, kafka, registry, scratch, fault=fail_once, lease_seconds=0.5)
    worker.run_once()
    assert failed["n"] == 1 and counts(db["posting"]) == (0, 0)  # rolled back: no posting, no outbox row
    assert parked_rows(db["posting"])[0]["status"] != "done"
    drain_parked(worker, db, timeout=30)
    assert counts(db["posting"]) == (1, 1)
    with db["ledger"].connect() as conn:
        assert credit_problems(conn, expected_credits(rec)) == []


def test_two_workers_never_claim_the_same_parked_event_and_each_posts_once(db, ledger, kafka, registry, scratch):
    members = [f"GR-{m:05d}" for m in range(1, 13)]
    records = {m: [stay(m, i * 100 + n) for n in range(1, 6)] for i, m in enumerate(members, start=1)}  # 60 events
    producer = checkout_producer(kafka, registry, scratch["input"])
    for n in range(5):
        for m in members:
            producer.send(records[m][n], flush=False)
    producer.flush()
    first_fails = {records[m][0]["stay_id"]: 1 for m in members}  # each member's first event parks; the rest follow
    loop = consumer_for(db, ledger, kafka, registry, scratch, wrap=lambda c: FlakyLedger(c, first_fails))
    assert run_until(loop, 60, timeout=120).count(Outcome.PARKED) == 60

    claims: list[tuple[str, list[int]]] = []
    lock = threading.Lock()
    workers = [make_worker(db, ledger, kafka, registry, scratch, worker_id=w, batch_size=4) for w in ("w-a", "w-b")]
    for worker in workers:
        original = worker.parked.claim

        def recording(worker_id, limit, lease_seconds, original=original):
            rows = original(worker_id, limit, lease_seconds)
            with lock:
                claims.append((worker_id, [r.id for r in rows]))
            return rows

        worker.parked.claim = recording
    errors: list[BaseException] = []

    def run(worker):
        try:
            drain_parked(worker, db, timeout=120)
        except BaseException as exc:  # reported below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(w,)) for w in workers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    claimed = [row_id for _, ids in claims for row_id in ids]
    assert len(claimed) == len(set(claimed)) == 60, "a parked event was claimed twice, or never"
    assert {name for name, ids in claims if ids} == {"w-a", "w-b"}, "one worker did all the work: nothing was tested"
    assert counts(db["posting"]) == (60, 60)
    assert postings_in_order(db["posting"]) == {m: [r["stay_id"] for r in records[m]] for m in members}
    with db["ledger"].connect() as conn:
        assert credit_problems(conn, expected_credits(*[r for m in members for r in records[m]])) == []


def test_a_long_ledger_outage_never_dead_letters_a_good_event(db, ledger, kafka, registry, scratch):
    rec = stay("GR-00001", 1)
    checkout_producer(kafka, registry, scratch["input"]).send(rec)
    loop = consumer_for(db, ledger, kafka, registry, scratch, wrap=lambda c: FlakyLedger(c, {rec["stay_id"]: 1}))
    assert run_until(loop, 1) == [Outcome.PARKED]
    worker = make_worker(
        db, ledger, kafka, registry, scratch, max_attempts=5, wrap=lambda c: FlakyLedger(c, {rec["stay_id"]: 12})
    )
    drain_parked(worker, db, timeout=60)
    [row] = parked_rows(db["posting"])
    assert (row["status"], row["attempts"], row["transient_failures"]) == ("done", 0, 13)  # 13 failures, never dead
    assert read_raw(kafka, scratch["dlq"], at_least=1, timeout=4) == []
    assert counts(db["posting"]) == (1, 1)


def test_parked_events_can_not_be_deleted_or_rewritten(db, ledger, kafka, registry, scratch):
    rec = stay("GR-00001", 1)
    checkout_producer(kafka, registry, scratch["input"]).send(rec)
    loop = consumer_for(db, ledger, kafka, registry, scratch, wrap=lambda c: FlakyLedger(c, {rec["stay_id"]: 1}))
    run_until(loop, 1)
    for statement in (
        "DELETE FROM parked_event",
        "UPDATE parked_event SET raw_value = 'x'::bytea",
        "UPDATE parked_event SET event_id = 'other'",
        "UPDATE outbox SET status = 'published', published_at = now()",
    ):
        with db["posting"].connect() as conn, pytest.raises(Exception, match="permission denied"):
            conn.execute(text(statement))
    with db["posting"].connect() as conn:
        assert conn.execute(select(outbox.c.id)).all() == []
