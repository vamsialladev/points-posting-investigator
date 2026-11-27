"""The posting service on the real stack: Kafka + Karapace, Postgres (test_posting, test_ledger), and the real ledger
app over HTTP (ADR-0015). Crash and concurrency tests are run 10 times by scripts\\repeat_tests.ps1 (verification log).
"""

from __future__ import annotations

import threading
import uuid

import pytest
from confluent_kafka import TopicPartition
from sqlalchemy import select, text

from app.pipeline import trace
from app.pipeline.posting import DatabaseFailure, IncomingMessage, Outcome, PostingCrash, make_consumer
from app.pipeline.tables import outbox
from tests.ledger_checks import credit_problems
from tests.pipeline_fixtures import expected_credits, stay
from tests.posting_helpers import (
    checkout_producer,
    counts,
    drain_parked,
    make_loop,
    make_service,
    make_worker,
    raw_producer,
    read_raw,
    run_until,
)
from tests.relay_helpers import drain, make_relay, open_rows, read_topic

pytestmark = [pytest.mark.postgres, pytest.mark.kafka]


def service_for(db, ledger, kafka, registry, scratch, fault=None):
    url, token = ledger
    return make_service(db["posting"], url, token, kafka, registry, scratch["output"], scratch["dlq"], fault=fault)


# ---------- happy path ----------


def test_one_event_gives_one_posting_one_outbox_row_and_one_published_message(db, ledger, kafka, registry, scratch):
    rec = stay("GR-00001", 1)
    sent = checkout_producer(kafka, registry, scratch["input"]).send(rec)
    loop = make_loop(
        service_for(db, ledger, kafka, registry, scratch), kafka, f"g-{uuid.uuid4().hex[:6]}", scratch["input"]
    )
    assert run_until(loop, 1) == [Outcome.POSTED]

    assert counts(db["posting"]) == (1, 1)
    with db["ledger"].connect() as conn:
        assert credit_problems(conn, expected_credits(rec)) == []
    relay = make_relay("r1", kafka, registry, db["relay"], scratch["output"])
    drain([relay], lambda: open_rows(db["relay"]) == 0)
    [message] = read_topic(kafka, registry, scratch["output"], at_least=1)
    assert message.value["source_event_id"] == sent.event_id == rec["event_id"]
    assert message.value["credited_points"] == 2_000
    assert trace.trace_id(message.headers["traceparent"]) == trace.trace_id(sent.traceparent)


# ---------- crashes and failures ----------


def test_a_crash_after_the_db_commit_before_the_offset_commit_redelivers_and_stays_one_posting(
    db, ledger, kafka, registry, scratch
):
    rec = stay("GR-00001", 1)
    checkout_producer(kafka, registry, scratch["input"]).send(rec)
    group = f"g-{uuid.uuid4().hex[:6]}"

    def crash(point: str) -> None:
        if point == "after_db_commit_before_offset_commit":
            raise PostingCrash(point)

    first = make_loop(service_for(db, ledger, kafka, registry, scratch, fault=crash), kafka, group, scratch["input"])
    with pytest.raises(PostingCrash):
        run_until(first, 1)
    first.consumer.close()  # closing doesn't commit: auto-commit is off
    assert counts(db["posting"]) == (1, 1)  # the database transaction had committed

    second = make_loop(service_for(db, ledger, kafka, registry, scratch), kafka, group, scratch["input"])
    assert run_until(second, 1) == [Outcome.DUPLICATE]  # redelivered, recognised, offset committed now
    assert counts(db["posting"]) == (1, 1)
    with db["ledger"].connect() as conn:
        assert credit_problems(conn, expected_credits(rec)) == []
    second.consumer.close()
    third = make_consumer(kafka, group, [scratch["input"]])
    committed = third.committed([TopicPartition(scratch["input"], p) for p in range(3)], timeout=10)
    third.close()
    assert sum(max(tp.offset, 0) for tp in committed) == 1  # exactly the one message is committed


def test_a_db_failure_mid_transaction_writes_neither_row_and_the_event_is_retried(db, ledger, kafka, registry, scratch):
    rec = stay("GR-00001", 1)
    checkout_producer(kafka, registry, scratch["input"]).send(rec)
    failed = {"n": 0}
    seen_after_failure: list[tuple[int, int]] = []

    def fail_once(point: str) -> None:
        if point == "mid_transaction" and failed["n"] == 0:
            failed["n"] += 1
            raise DatabaseFailure("simulated failure between the posting and the outbox insert")

    loop = make_loop(
        service_for(db, ledger, kafka, registry, scratch, fault=fail_once),
        kafka,
        "g-" + uuid.uuid4().hex[:6],
        scratch["input"],
    )
    outcomes = []
    while Outcome.POSTED not in outcomes:
        outcome = loop.run_once(timeout=0.5)
        if outcome is Outcome.RETRY:
            seen_after_failure.append(counts(db["posting"]))
        if outcome is not None:
            outcomes.append(outcome)
    assert outcomes == [Outcome.RETRY, Outcome.POSTED]
    assert seen_after_failure == [(0, 0)]  # the rollback took the posting row with it: neither row written
    assert counts(db["posting"]) == (1, 1)
    with db["ledger"].connect() as conn:
        assert credit_problems(conn, expected_credits(rec)) == []  # the retry got the same ledger entry back


# ---------- duplicates ----------


def test_the_same_event_twice_gives_one_posting(db, ledger, kafka, registry, scratch):
    rec = stay("GR-00001", 1)
    producer = checkout_producer(kafka, registry, scratch["input"])
    producer.send(rec)
    producer.send(rec)  # a resend keeps its event_id
    loop = make_loop(
        service_for(db, ledger, kafka, registry, scratch), kafka, "g-" + uuid.uuid4().hex[:6], scratch["input"]
    )
    assert run_until(loop, 2) == [Outcome.POSTED, Outcome.DUPLICATE]
    assert counts(db["posting"]) == (1, 1)
    with db["ledger"].connect() as conn:
        assert credit_problems(conn, expected_credits(rec)) == []


def concurrent_copies(service, messages: list[IncomingMessage]) -> tuple[list[Outcome], list[BaseException]]:
    outcomes: list[Outcome] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(len(messages))

    def work(message: IncomingMessage) -> None:
        barrier.wait()
        try:
            outcomes.append(service.handle(message))
        except BaseException as exc:  # asserted on by the caller
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(m,)) for m in messages]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return outcomes, errors


def as_incoming(kafka_message) -> IncomingMessage:
    return IncomingMessage.from_kafka(kafka_message)


def test_eight_concurrent_copies_of_one_event_give_one_posting(db, ledger, kafka, registry, scratch):
    rec = stay("GR-00001", 1)
    checkout_producer(kafka, registry, scratch["input"]).send(rec)
    [message] = read_raw(kafka, scratch["input"], at_least=1)
    service = service_for(db, ledger, kafka, registry, scratch)
    outcomes, errors = concurrent_copies(service, [as_incoming(message)] * 8)
    assert errors == []
    assert sorted(outcomes) == sorted([Outcome.POSTED] + [Outcome.DUPLICATE] * 7)
    assert counts(db["posting"]) == (1, 1)
    with db["ledger"].connect() as conn:
        assert credit_problems(conn, expected_credits(rec)) == []


def test_eight_concurrent_resends_under_new_event_ids_give_one_credit_and_one_posting(
    db, ledger, kafka, registry, scratch
):
    """Change 1 (2026-11-23): the ledger key is the stay, so a re-emitted stay can't be credited twice in a race."""
    base = stay("GR-00001", 1)
    copies = [{**base, "event_id": str(uuid.uuid4())} for _ in range(8)]
    producer = checkout_producer(kafka, registry, scratch["input"])
    for rec in copies:
        producer.send(rec)
    messages = read_raw(kafka, scratch["input"], at_least=8)
    service = service_for(db, ledger, kafka, registry, scratch)
    outcomes, errors = concurrent_copies(service, [as_incoming(m) for m in messages])
    assert errors == []
    assert sorted(outcomes) == sorted([Outcome.POSTED] + [Outcome.DUPLICATE] * 7)
    assert counts(db["posting"]) == (1, 1)
    with db["ledger"].connect() as conn:
        assert credit_problems(conn, expected_credits(base)) == []  # one credit for the stay, not eight


# ---------- poison ----------


def test_an_undecodable_event_is_dead_lettered_and_the_next_event_flows(db, ledger, kafka, registry, scratch):
    raw = raw_producer(kafka)
    raw.produce(scratch["input"], key=b"GR-00009", value=b"\x00not-avro", headers=[("event_id", b"bad-1")])
    raw.flush(10)
    good = stay("GR-00002", 2)
    checkout_producer(kafka, registry, scratch["input"]).send(good)
    loop = make_loop(
        service_for(db, ledger, kafka, registry, scratch), kafka, "g-" + uuid.uuid4().hex[:6], scratch["input"]
    )
    outcomes = run_until(loop, 2)
    assert sorted(outcomes) == sorted([Outcome.DEAD_LETTERED, Outcome.POSTED])
    assert counts(db["posting"]) == (1, 1)
    [dead] = read_raw(kafka, scratch["dlq"], at_least=1)
    headers = {k: v.decode() for k, v in dead.headers()}
    assert dead.value() == b"\x00not-avro" and dead.key() == b"GR-00009"  # the original bytes, untouched
    assert headers["error_class"] == "schema" and headers["event_id"] == "bad-1" and headers["attempt"] == "1"
    assert headers["original_topic"] == scratch["input"]


def test_corrections_credit_the_difference_and_a_stale_revision_is_skipped(db, ledger, kafka, registry, scratch):
    """D10 (catalog scenario 11), replacing B2a's "dead-lettered until PR-C". Revisions 1, 3, then 2 of one stay:
    1 credits the stay, 3 the difference from 1, and 2 (now stale) is recorded and not credited."""
    original = stay("GR-00001", 1, room_rate_cents=40_000)  # 4,000 points
    third = stay("GR-00001", 1, room_rate_cents=46_000, revision=3)  # 4,600: +600
    second = stay("GR-00001", 1, room_rate_cents=10_000, revision=2)  # arrives last: stale
    producer = checkout_producer(kafka, registry, scratch["input"])
    for rec in (original, third, second):
        producer.send(rec)
    loop = make_loop(
        service_for(db, ledger, kafka, registry, scratch), kafka, "g-" + uuid.uuid4().hex[:6], scratch["input"]
    )
    assert run_until(loop, 3) == [Outcome.POSTED, Outcome.POSTED, Outcome.SKIPPED]  # one member: one partition

    with db["ledger"].connect() as conn:
        assert credit_problems(conn, {"BR-0001:1": 4_000, "BR-0001:3": 600}) == []
        assert conn.execute(text("SELECT sum(points) FROM credits")).scalar() == 4_600  # what revision 3 earns
    with db["posting"].connect() as conn:
        skipped = conn.execute(text("SELECT event_id, revision, latest_revision FROM skipped_event")).all()
    assert [tuple(r) for r in skipped] == [(second["event_id"], 2, 3)]
    relay = make_relay("r1", kafka, registry, db["relay"], scratch["output"])
    drain([relay], lambda: open_rows(db["relay"]) == 0)
    received = read_topic(kafka, registry, scratch["output"], at_least=2)
    assert sorted(m.value["credited_points"] for m in received) == [600, 4_000]


def test_a_correction_before_its_original_is_retried_then_dead_lettered_as_original_missing(
    db, ledger, kafka, registry, scratch
):
    """RFC-0001 test 12: nothing posted for the stay, so the correction is parked, retried to the maximum, and sent to
    the DLQ with its original bytes. Nothing is credited."""
    rec = stay("GR-00001", 1, revision=2)
    checkout_producer(kafka, registry, scratch["input"]).send(rec)
    loop = make_loop(
        service_for(db, ledger, kafka, registry, scratch), kafka, "g-" + uuid.uuid4().hex[:6], scratch["input"]
    )
    assert run_until(loop, 1) == [Outcome.PARKED]
    worker = make_worker(db, ledger, kafka, registry, scratch)
    drain_parked(worker, db)
    [dead] = read_raw(kafka, scratch["dlq"], at_least=1)
    headers = dict((k, v.decode()) for k, v in dead.headers())
    assert (headers["error_class"], headers["attempt"]) == ("original_missing", "5")
    assert headers["event_id"] == rec["event_id"]
    assert counts(db["posting"]) == (0, 0)
    with db["ledger"].connect() as conn:
        assert credit_problems(conn, {}) == []  # nothing credited


def test_the_posting_role_can_not_change_or_delete_a_skipped_event(db):
    for statement in ("UPDATE skipped_event SET revision = 9", "DELETE FROM skipped_event"):
        with db["posting"].connect() as conn, pytest.raises(Exception, match="permission denied"):
            conn.execute(text(statement))


def test_a_ledger_outage_parks_the_event_commits_the_offset_and_the_worker_posts_it_later(
    db, ledger, kafka, registry, scratch
):
    """B2b (ADR-0016): the event is parked and its offset committed, so the partition moves on; it posts once later."""
    _, token = ledger
    rec = stay("GR-00001", 1)
    checkout_producer(kafka, registry, scratch["input"]).send(rec)
    group = "g-" + uuid.uuid4().hex[:6]
    down = make_service(db["posting"], "http://127.0.0.1:9", token, kafka, registry, scratch["output"], scratch["dlq"])
    loop = make_loop(down, kafka, group, scratch["input"])
    assert run_until(loop, 1) == [Outcome.PARKED]
    assert counts(db["posting"]) == (0, 0)
    loop.consumer.close()
    later = make_consumer(kafka, group, [scratch["input"]])
    committed = later.committed([TopicPartition(scratch["input"], p) for p in range(3)], timeout=10)
    later.close()
    assert sum(max(tp.offset, 0) for tp in committed) == 1  # the offset moved on: nothing blocks the partition

    worker = make_worker(db, ledger, kafka, registry, scratch)
    drain_parked(worker, db)
    assert counts(db["posting"]) == (1, 1)
    with db["ledger"].connect() as conn:
        assert credit_problems(conn, expected_credits(rec)) == []


# ---------- end to end ----------


def test_end_to_end_one_trace_id_from_producer_to_points_posted(db, ledger, kafka, registry, scratch):
    records = [stay(f"GR-0000{m}", m * 10 + n) for m in (1, 2, 3) for n in (1, 2)]  # one stay ID per stay
    producer = checkout_producer(kafka, registry, scratch["input"])
    sent = {rec["event_id"]: producer.send(rec) for rec in records}
    loop = make_loop(
        service_for(db, ledger, kafka, registry, scratch), kafka, "g-" + uuid.uuid4().hex[:6], scratch["input"]
    )
    assert run_until(loop, 6) == [Outcome.POSTED] * 6

    with db["posting"].connect() as conn:
        stored = {r.payload["source_event_id"]: r.trace_context for r in conn.execute(select(outbox))}
    relay = make_relay("r1", kafka, registry, db["relay"], scratch["output"])
    drain([relay], lambda: open_rows(db["relay"]) == 0)
    received = read_topic(kafka, registry, scratch["output"], at_least=6)
    assert len(received) == 6
    for message in received:
        source = message.value["source_event_id"]
        producer_trace = trace.trace_id(sent[source].traceparent)
        assert trace.trace_id(stored[source]["traceparent"]) == producer_trace  # posting service -> outbox row
        assert trace.trace_id(message.headers["traceparent"]) == producer_trace  # relay -> Kafka headers
        assert stored[source]["traceparent"] != sent[source].traceparent  # each hop is its own span
    with db["ledger"].connect() as conn:
        assert credit_problems(conn, expected_credits(*records)) == []
        assert conn.execute(text("SELECT count(DISTINCT idempotency_key) FROM credits")).scalar_one() == 6
