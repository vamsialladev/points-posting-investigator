"""The outbox relay on the real stack: Postgres (test_posting) and Kafka with Karapace (ADR-0014).

Each test writes outbox rows as the posting service role would, runs one or more relays as the relay role, and reads
the scratch topic back. Crash and concurrency tests are run 10 times by scripts\\repeat_tests.ps1 (verification log).
"""

from __future__ import annotations

import collections
import json
import subprocess
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from confluent_kafka.admin import AdminClient
from confluent_kafka.schema_registry import Schema
from sqlalchemy import Engine, create_engine, text

from app.pipeline import topics, trace
from app.pipeline.relay import OutboxStore, RelayCrash
from tests.infra import POSTING, admin_connect, admin_kafka, role_url
from tests.relay_helpers import (
    drain,
    make_relay,
    open_rows,
    per_member_order,
    read_topic,
    rows_by_id,
    write_rows,
)
from tests.test_kafka_stack import drop_subject

pytestmark = [pytest.mark.postgres, pytest.mark.kafka]
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def writer(admin, passwords, host) -> Iterator[Engine]:
    with admin_connect(admin, POSTING) as conn:
        conn.execute("TRUNCATE outbox RESTART IDENTITY")
    engine = create_engine(role_url(POSTING, passwords, host, "app"))
    yield engine
    engine.dispose()


@pytest.fixture
def relay_db(passwords, host) -> Iterator[Engine]:
    engine = create_engine(role_url(POSTING, passwords, host, "relay"), pool_size=8)
    yield engine
    engine.dispose()


@pytest.fixture
def topic(kafka, registry) -> Iterator[str]:
    name = f"test.relay.{uuid.uuid4().hex[:10]}"
    topics.ensure_topics(kafka, (topics.TopicSpec(name),))
    yield name
    AdminClient(admin_kafka(kafka)).delete_topics([name], operation_timeout=30)
    drop_subject(registry, f"{name}-value")


def test_one_row_becomes_one_message_with_its_trace_and_the_lag_drops_to_zero(writer, relay_db, kafka, registry, topic):
    [row] = write_rows(writer, topic, [("GR-00001", 1)])
    relay = make_relay("r1", kafka, registry, relay_db, topic)
    time.sleep(1.2)
    assert relay.store.stats().oldest_unpublished_age_seconds >= 1.0  # the lag metric sees the waiting row

    drain([relay], lambda: open_rows(relay_db) == 0)

    [message] = read_topic(kafka, registry, topic, at_least=1)
    assert message.key == "GR-00001" and message.value["event_id"] == row.event_id
    assert message.headers["event_id"] == row.event_id and message.headers["outbox_id"] == str(row.id)
    assert message.headers["correlation_id"] == "corr-GR-00001-1"
    assert trace.trace_id(message.headers["traceparent"]) == trace.trace_id(row.traceparent)  # same trace, child span
    stored = rows_by_id(relay_db)[row.id]
    assert (stored["status"], stored["claimed_by"], stored["attempts"]) == ("published", "r1", 0)
    assert stored["published_at"] is not None and stored["lease_until"] is None
    stats = relay.store.stats()
    assert (stats.unpublished, stats.dead, stats.oldest_unpublished_age_seconds) == (0, 0, 0.0)


def test_two_relays_never_claim_the_same_row_and_each_row_is_published_once(writer, relay_db, kafka, registry, topic):
    members = [f"GR-{n:05d}" for n in range(1, 21)]
    written = write_rows(writer, topic, [(m, seq) for seq in range(1, 11) for m in members])  # 200 rows, interleaved
    claims: list[tuple[str, list[int]]] = []
    lock = threading.Lock()

    def recording(relay):
        original = relay.store.claim

        def claim(relay_id, limit, lease_seconds):
            rows = original(relay_id, limit, lease_seconds)
            with lock:
                claims.append((relay_id, [r.id for r in rows]))
            return rows

        relay.store.claim = claim
        return relay

    relays = [recording(make_relay(name, kafka, registry, relay_db, topic, batch_size=7)) for name in ("r-a", "r-b")]
    errors: list[BaseException] = []

    def run(relay):
        try:
            drain([relay], lambda: open_rows(relay_db) == 0, timeout=120)
        except BaseException as exc:  # reported below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(relay,)) for relay in relays]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []

    claimed = [row_id for _, ids in claims for row_id in ids]
    assert sorted(claimed) == sorted(w.id for w in written), "a row was claimed twice, or never"
    assert {name for name, ids in claims if ids} == {"r-a", "r-b"}, "one relay did all the work: nothing was tested"

    received = read_topic(kafka, registry, topic, at_least=200)
    counts = collections.Counter(m.value["event_id"] for m in received)
    assert len(counts) == 200 and set(counts.values()) == {1}, "a row was published by both relays"
    assert per_member_order(received) == {m: list(range(1, 11)) for m in members}


def test_a_crash_after_publish_before_marking_publishes_twice_and_readers_dedupe(
    writer, relay_db, kafka, registry, topic
):
    written = write_rows(writer, topic, [("GR-00001", 1), ("GR-00002", 1), ("GR-00003", 1)])

    def crash(point: str) -> None:
        if point == "after_publish_before_mark":
            raise RelayCrash(point)

    with pytest.raises(RelayCrash):
        make_relay("r-crashed", kafka, registry, relay_db, topic, lease_seconds=1.0, fault=crash).run_once()
    assert {r["status"] for r in rows_by_id(relay_db).values()} == {"in_flight"}  # published, never marked

    time.sleep(1.5)  # the crashed relay's lease runs out
    survivor = make_relay("r-survivor", kafka, registry, relay_db, topic, lease_seconds=1.0)
    drain([survivor], lambda: open_rows(relay_db) == 0)

    received = read_topic(kafka, registry, topic, at_least=6)
    counts = collections.Counter(m.value["event_id"] for m in received)
    assert counts == {w.event_id: 2 for w in written}  # the documented duplicate: at least once, not exactly once
    assert len({m.value["event_id"] for m in received}) == 3  # a reader deduping on event_id sees each once
    assert {r["claimed_by"] for r in rows_by_id(relay_db).values()} == {"r-survivor"}


def test_a_crash_after_claiming_before_publishing_is_published_once_after_the_lease(
    writer, relay_db, kafka, registry, topic
):
    written = write_rows(writer, topic, [("GR-00001", 1), ("GR-00001", 2)])

    def crash(point: str) -> None:
        if point == "after_claim":
            raise RelayCrash(point)

    with pytest.raises(RelayCrash):
        make_relay("r-crashed", kafka, registry, relay_db, topic, lease_seconds=1.0, fault=crash).run_once()
    survivor = make_relay("r-survivor", kafka, registry, relay_db, topic, lease_seconds=1.0)
    survivor.run_once()
    assert open_rows(relay_db) == 2, "claimed rows must wait for the lease, not be taken over early"
    time.sleep(1.5)
    drain([survivor], lambda: open_rows(relay_db) == 0)

    received = read_topic(kafka, registry, topic, at_least=2)
    assert [m.value["event_id"] for m in received] == [w.event_id for w in written]  # once each, in order


def test_per_member_order_holds_while_one_row_retries(writer, relay_db, kafka, registry, topic):
    written = write_rows(writer, topic, [("GR-00001", s) for s in range(1, 5)])
    others = write_rows(writer, topic, [("GR-00002", s) for s in range(1, 4)])
    first = written[0].id
    failures_left = {"n": 3}

    def flaky(row) -> None:
        if row.id == first and failures_left["n"] > 0:
            failures_left["n"] -= 1
            raise BufferError("simulated full producer queue (transient)")

    relay = make_relay("r1", kafka, registry, relay_db, topic, before_produce=flaky)
    drain([relay], lambda: open_rows(relay_db) == 0)

    received = read_topic(kafka, registry, topic, at_least=7)
    assert per_member_order(received) == {"GR-00001": [1, 2, 3, 4], "GR-00002": [1, 2, 3]}
    stored = rows_by_id(relay_db)
    assert stored[first]["attempts"] == 0  # transient failures don't count toward the dead-letter limit
    assert max(stored[o.id]["published_at"] for o in others) < stored[first]["published_at"], (
        "the other member waited for this member's retries"
    )


def test_a_poison_row_is_dead_lettered_after_max_attempts_and_nothing_else_waits_for_good(
    writer, relay_db, kafka, registry, topic
):
    p_rows = write_rows(writer, topic, [("GR-00001", s) for s in (1, 2, 3)], poison={1})
    q_rows = write_rows(writer, topic, [("GR-00002", s) for s in (1, 2, 3)])
    relay = make_relay("r1", kafka, registry, relay_db, topic, max_attempts=5)
    drain([relay], lambda: open_rows(relay_db) == 0)

    stored = rows_by_id(relay_db)
    dead = stored[p_rows[0].id]
    assert (dead["status"], dead["attempts"]) == ("dead", 5)
    assert dead["dead_at"] is not None and "SerializationError" in dead["last_error"]
    assert max(stored[q.id]["published_at"] for q in q_rows) < dead["dead_at"], "another member waited on the poison"
    assert all(stored[p.id]["published_at"] > dead["dead_at"] for p in p_rows[1:])  # unblocked once it died

    received = read_topic(kafka, registry, topic, at_least=5)
    assert per_member_order(received) == {"GR-00001": [2, 3], "GR-00002": [1, 2, 3]}
    stats = relay.store.stats()
    assert (stats.unpublished, stats.dead) == (0, 1)
    assert "outbox_dead_rows 1.0" in relay.metrics.render().decode()


# ---------- Kafka down for 60 s ----------


def compose(*args: str) -> None:
    subprocess.run(["docker", "compose", "--profile", "core", *args], cwd=ROOT, check=True, capture_output=True)


def wait_for_kafka(kafka: str, timeout: float = 180.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            AdminClient(admin_kafka(kafka)).list_topics(timeout=3)
            return
        except Exception:  # still starting
            time.sleep(2)
    raise AssertionError("Kafka did not come back")


def wait_for_registry(registry, timeout: float = 300.0) -> float:
    """Karapace 6.2.4 answers TimeoutError for a while after Kafka restarts (it re-reads `_schemas`). Wait until a
    probe subject can be registered and deleted; return how long that took (printed into the verification log)."""
    probe = json.dumps({"type": "record", "name": "Probe", "fields": [{"name": "a", "type": "string"}]})
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        subject = f"probe-{uuid.uuid4().hex[:8]}-value"
        try:
            registry.register_schema(subject, Schema(probe, "AVRO"))
            drop_subject(registry, subject)
            return time.monotonic() - start
        except Exception:  # still recovering
            time.sleep(2)
    raise AssertionError(f"the schema registry didn't accept writes within {timeout} s of Kafka returning")


@pytest.mark.chaos
def test_kafka_down_for_60_seconds_the_outbox_grows_then_drains_with_nothing_lost(
    writer, relay_db, kafka, registry, topic
):
    warm = write_rows(writer, topic, [("GR-00099", 1)])  # registers the schema while Kafka is up (own member)
    relay = make_relay("r1", kafka, registry, relay_db, topic, delivery_timeout=5.0)
    drain([relay], lambda: open_rows(relay_db) == 0)

    stop = threading.Event()
    loop = threading.Thread(target=relay.run, args=(stop,), kwargs={"poll_interval": 0.5})
    loop.start()
    try:
        compose("stop", "kafka")
        outage_start = time.monotonic()
        during = write_rows(writer, topic, [(f"GR-{n:05d}", s) for s in (1, 2, 3) for n in range(1, 11)])  # 30 rows
        time.sleep(max(0.0, 60.0 - (time.monotonic() - outage_start)))
        stats = relay.store.stats()
        assert stats.unpublished == 30 and stats.oldest_unpublished_age_seconds >= 55.0
        compose("start", "kafka")
        wait_for_kafka(kafka)
        deadline = time.monotonic() + 120
        while open_rows(relay_db) and time.monotonic() < deadline:
            time.sleep(1)
        drained_after = time.monotonic() - outage_start
    finally:
        stop.set()
        loop.join(timeout=30)
        compose("start", "kafka")  # whatever happened above, leave Kafka running for the next test
        wait_for_kafka(kafka)
        registry_after = wait_for_registry(registry)  # reading the topic back needs the registry too

    stats = relay.store.stats()
    assert (stats.unpublished, stats.dead, stats.oldest_unpublished_age_seconds) == (0, 0, 0.0)
    stored = rows_by_id(relay_db)
    assert {r["status"] for r in stored.values()} == {"published"}
    assert {r["attempts"] for r in stored.values()} == {0}  # the outage was never counted as poison
    received = read_topic(kafka, registry, topic, at_least=31)
    assert {m.value["event_id"] for m in received} == {w.event_id for w in warm + during}  # nothing lost
    assert per_member_order(received) == {"GR-00099": [1], **{f"GR-{n:05d}": [1, 2, 3] for n in range(1, 11)}}
    duplicates = len(received) - 31
    print(  # recorded in the verification log
        f"evidence: {duplicates} duplicate message(s) on the topic; outbox drained {drained_after:.0f} s after the"
        f" outage began; registry writable after {registry_after:.0f} s more (clock starts once the outbox drained)"
    )


def test_the_relay_role_only_changes_delivery_state(writer, relay_db, passwords, host):
    [row] = write_rows(writer, "points.posted", [("GR-00001", 1)])
    with relay_db.begin() as conn:
        conn.execute(text("UPDATE outbox SET next_attempt_at = now() WHERE id = :id"), {"id": row.id})
    for statement in (
        "UPDATE outbox SET payload = '{}'::jsonb",
        "UPDATE outbox SET topic = 'elsewhere'",
        "DELETE FROM outbox",
        "INSERT INTO outbox (topic, message_key, payload) VALUES ('t', 'k', '{}'::jsonb)",
        "SELECT * FROM posting",
    ):
        with relay_db.connect() as conn, pytest.raises(Exception, match="permission denied"):
            conn.execute(text(statement))
    assert isinstance(OutboxStore(relay_db).stats().unpublished, int)


@pytest.mark.parametrize(
    "broken",
    [
        "UPDATE outbox SET status = 'published'",  # published without published_at
        "UPDATE outbox SET status = 'dead'",  # dead without dead_at
        "UPDATE outbox SET status = 'in_flight'",  # in flight without a lease
        "UPDATE outbox SET status = 'lost'",  # not a status
    ],
)
def test_the_database_refuses_an_inconsistent_delivery_state(writer, admin, broken):
    write_rows(writer, "points.posted", [("GR-00001", 1)])
    with admin_connect(admin, POSTING) as conn, pytest.raises(Exception, match="violates check constraint"):
        conn.execute(broken)
