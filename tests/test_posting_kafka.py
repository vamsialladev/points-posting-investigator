"""The posting service on the real stack: Kafka + Karapace, Postgres (test_posting, test_ledger), and the real ledger
app over HTTP (ADR-0015). Crash and concurrency tests are run 10 times by scripts\\repeat_tests.ps1 (verification log).
"""

from __future__ import annotations

import secrets
import threading
import uuid
from collections.abc import Iterator
from datetime import date

import pytest
from confluent_kafka import TopicPartition
from confluent_kafka.admin import AdminClient
from sqlalchemy import Engine, create_engine, select, text

from app.pipeline import topics, trace
from app.pipeline.events import ledger_key, points_for, validate
from app.pipeline.posting import DatabaseFailure, IncomingMessage, Outcome, PostingCrash, make_consumer
from app.pipeline.producer import build_event
from app.pipeline.tables import outbox
from tests.infra import LEDGER, POSTING, admin_connect, role_url
from tests.ledger_checks import credit_problems
from tests.posting_helpers import (
    checkout_producer,
    counts,
    ledger_server,
    make_loop,
    make_service,
    raw_producer,
    read_raw,
    run_until,
)
from tests.relay_helpers import drain, make_relay, open_rows, read_topic
from tests.test_kafka_stack import drop_subject

pytestmark = [pytest.mark.postgres, pytest.mark.kafka]


@pytest.fixture
def db(admin, passwords, host) -> Iterator[dict[str, Engine]]:
    with admin_connect(admin, POSTING) as conn:
        conn.execute("TRUNCATE posting, outbox RESTART IDENTITY")
    with admin_connect(admin, LEDGER) as conn:
        conn.execute("TRUNCATE credits")
    engines = {
        "posting": create_engine(role_url(POSTING, passwords, host, "app"), pool_size=10),
        "relay": create_engine(role_url(POSTING, passwords, host, "relay")),
        "ledger": create_engine(role_url(LEDGER, passwords, host), pool_size=10),
    }
    yield engines
    for engine in engines.values():
        engine.dispose()


@pytest.fixture
def ledger(db) -> Iterator[tuple[str, str]]:
    token = secrets.token_urlsafe(18)
    with ledger_server(db["ledger"], token) as url:
        yield url, token


@pytest.fixture
def scratch(kafka, registry) -> Iterator[dict[str, str]]:
    tag = uuid.uuid4().hex[:10]
    names = {"input": f"test.in.{tag}", "output": f"test.out.{tag}", "dlq": f"test.dlq.{tag}"}
    topics.ensure_topics(kafka, tuple(topics.TopicSpec(name) for name in names.values()))
    yield names
    AdminClient({"bootstrap.servers": kafka}).delete_topics(list(names.values()), operation_timeout=30)
    for name in names.values():
        drop_subject(registry, f"{name}-value")


def stay(member: str, n: int, **changes) -> dict:
    prefix, prop = ("BR", "beach-resort") if n % 2 else ("ML", "mountain-lodge")
    return build_event(
        member_number=member,
        stay_id=f"{prefix}-{n:04d}",
        property=prop,
        check_in=date(2026, 11, 14),
        nights=2,
        room_rate_cents=20_000 + n,
        **changes,
    )


def expected_credits(*records: dict) -> dict[str, int]:
    events = [validate(r, {"event_id": r["event_id"], "schema_version": "1"}) for r in records]
    return {ledger_key(e): points_for(e) for e in events}


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


def test_a_correction_is_dead_lettered_until_pr_c(db, ledger, kafka, registry, scratch):
    rec = stay("GR-00001", 1, revision=2)
    checkout_producer(kafka, registry, scratch["input"]).send(rec)
    loop = make_loop(
        service_for(db, ledger, kafka, registry, scratch), kafka, "g-" + uuid.uuid4().hex[:6], scratch["input"]
    )
    assert run_until(loop, 1) == [Outcome.DEAD_LETTERED]
    [dead] = read_raw(kafka, scratch["dlq"], at_least=1)
    assert dict((k, v.decode()) for k, v in dead.headers())["error_class"] == "unsupported_revision"
    assert counts(db["posting"]) == (0, 0)
    with db["ledger"].connect() as conn:
        assert credit_problems(conn, {}) == []  # nothing credited


def test_a_ledger_outage_is_retried_in_place_without_committing(db, ledger, kafka, registry, scratch):
    """B2a behaviour (B2b parks instead): the event waits, nothing is written, then it posts once."""
    _, token = ledger
    rec = stay("GR-00001", 1)
    checkout_producer(kafka, registry, scratch["input"]).send(rec)
    group = "g-" + uuid.uuid4().hex[:6]
    down = make_service(db["posting"], "http://127.0.0.1:9", token, kafka, registry, scratch["output"], scratch["dlq"])
    loop = make_loop(down, kafka, group, scratch["input"])
    assert [loop.run_once(timeout=5.0) for _ in range(3)].count(Outcome.RETRY) >= 2
    assert counts(db["posting"]) == (0, 0)
    loop.consumer.close()
    up = make_loop(service_for(db, ledger, kafka, registry, scratch), kafka, group, scratch["input"])
    assert run_until(up, 1) == [Outcome.POSTED]
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
