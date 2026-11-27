"""Scenarios triggered and reset on the real stack: the containerised posting service, retry worker, relay and ledger.

A fast subset runs here on every CI run: S01, S02, S05, S11, S13, S16. Each asserts the evidence the pre-registered
catalog says the scenario leaves, read from the databases and the dead-letter topic. The slower scenarios (restarts,
a database outage, a rebalance storm) are run in a batch on the owner's machine (verification log).

Needs TEST_DATABASE_URL, TEST_KAFKA_BOOTSTRAP_SERVERS, TEST_SCHEMA_REGISTRY_URL, TEST_LEDGER_URL, TEST_LEDGER_TOKEN
(scripts\\test_integration.ps1 sets them without printing them). These tests write synthetic rows into the stack's own
databases, in blocks of members and stays no other test or demo run uses.
"""

from __future__ import annotations

import os

import pytest

from app.scenarios import plans, run, steps
from app.scenarios.executor import Executor

pytestmark = [pytest.mark.postgres, pytest.mark.kafka]
RUNS_FOR_TESTS = range(plans.MAX_RUN, 5, -1)  # the top of the range; demo runs count up from 0
MAPPING = {
    "DATABASE_URL": "TEST_DATABASE_URL",
    "KAFKA_BOOTSTRAP_SERVERS": "TEST_KAFKA_BOOTSTRAP_SERVERS",
    "SCHEMA_REGISTRY_URL": "TEST_SCHEMA_REGISTRY_URL",
    "LEDGER_API_URL": "TEST_LEDGER_URL",
    "LEDGER_API_TOKEN": "TEST_LEDGER_TOKEN",
}


@pytest.fixture(scope="module")
def effects():
    env = {name: os.environ.get(source, "") for name, source in MAPPING.items()}
    missing = [MAPPING[name] for name, value in env.items() if not value]
    if missing:
        pytest.skip(f"{', '.join(missing)} not set: run scripts\\stack.ps1 up, then scripts\\test_integration.ps1")
    return run.stack_effects(env)


def rows(effects, base: str, query: str, params: tuple = ()) -> list[tuple]:
    with effects.connect(base) as conn:
        return conn.execute(query, params).fetchall()


def free_run(effects, scenario: str) -> int:
    """The first run of this scenario that left nothing on this stack yet, so the trigger behaves as on a new one."""
    for number in RUNS_FOR_TESTS:
        manifest = plans.plan(scenario, number).manifest
        ids = [event.event_id for event in manifest.events]
        if ids:
            used = rows(effects, "posting", "SELECT 1 FROM posting WHERE event_id = ANY(%s) LIMIT 1", (ids,))
            used += rows(effects, "posting", "SELECT 1 FROM parked_event WHERE event_id = ANY(%s) LIMIT 1", (ids,))
            used += [1] if set(ids) & effects.kafka.dead_letter_event_ids() else []
        else:
            member = manifest.affected[0].member_number
            used = rows(effects, "ops", "SELECT 1 FROM member_question WHERE member_number = %s LIMIT 1", (member,))
        if not used:
            return number
    pytest.fail(f"every test run of {scenario} is used on this stack: scripts\\stack.ps1 reset clears it (ask first)")


def trigger_then_reset(effects, scenario: str, tmp_path) -> plans.Plan:
    built = plans.plan(scenario, free_run(effects, scenario))
    number = built.manifest.run
    said: list[str] = []
    for phase in ("trigger", "reset"):
        ok = run.execute(phase, scenario, number, None, effects, directory=tmp_path, say=said.append,
                         executor=Executor(effects, poll_seconds=0.5))  # fmt: skip
        assert ok, "\n".join(said)
    return built


def credits_for(effects, events) -> dict[str, int]:
    keys = [f"{event.stay_id}:{event.revision}" for event in events]
    found = rows(effects, "ledger", "SELECT idempotency_key FROM credits WHERE idempotency_key = ANY(%s)", (keys,))
    counts: dict[str, int] = {}
    for (key,) in found:
        counts[key] = counts.get(key, 0) + 1
    return counts


def test_s01_bad_events_are_dead_lettered_at_once_and_never_posted_or_credited(effects, tmp_path):
    built = trigger_then_reset(effects, "S01", tmp_path)
    bad = [e for e in built.manifest.events if e.kind != steps.VALID]
    good = [e for e in built.manifest.events if e.kind == steps.VALID]
    bad_ids = [e.event_id for e in bad]
    assert set(bad_ids) <= effects.kafka.dead_letter_event_ids()
    assert rows(effects, "posting", "SELECT 1 FROM posting WHERE event_id = ANY(%s)", (bad_ids,)) == []
    assert rows(effects, "posting", "SELECT 1 FROM parked_event WHERE event_id = ANY(%s)", (bad_ids,)) == []
    assert credits_for(effects, bad) == {}
    assert credits_for(effects, good) == {f"{e.stay_id}:1": 1 for e in good}
    assert {a.member_number for a in built.manifest.affected} == {e.member_number for e in bad}


def test_s02_duplicates_post_once_and_credit_once(effects, tmp_path):
    built = trigger_then_reset(effects, "S02", tmp_path)
    events = built.manifest.events
    assert sum(e.copies for e in events) > len(events)
    ids = [e.event_id for e in events]
    posted = rows(effects, "posting", "SELECT event_id FROM posting WHERE event_id = ANY(%s)", (ids,))
    assert sorted(r[0] for r in posted) == sorted(ids), "one posting per event, however often it was delivered"
    assert credits_for(effects, events) == {f"{e.stay_id}:1": 1 for e in events}


def test_s05_the_poison_event_is_dead_after_five_attempts_and_the_event_behind_it_posts(effects, tmp_path):
    built = trigger_then_reset(effects, "S05", tmp_path)
    poison = max(built.manifest.events, key=lambda e: e.room_rate_cents)
    parked = rows(
        effects,
        "posting",
        "SELECT status, attempts, error_class FROM parked_event WHERE event_id = %s",
        (poison.event_id,),
    )
    assert parked == [("dead", 5, "ledger_rejected_422")], "the class and count the catalog pre-registered"
    assert poison.event_id in effects.kafka.dead_letter_event_ids()
    others = [e for e in built.manifest.events if e is not poison]
    assert credits_for(effects, built.manifest.events) == {f"{e.stay_id}:1": 1 for e in others}
    behind = next(e for e in others if e.member_number == poison.member_number)
    assert rows(effects, "posting", "SELECT 1 FROM posting WHERE event_id = %s", (behind.event_id,)) == [(1,)]
    assert [(a.member_number, a.effect) for a in built.manifest.affected] == [(poison.member_number, steps.NOT_POSTED)]


def test_s11_the_correction_is_dead_lettered_as_original_missing_and_the_original_posts(effects, tmp_path):
    built = trigger_then_reset(effects, "S11", tmp_path)
    (correction_id,) = built.manifest.replay_event_ids
    correction = next(e for e in built.manifest.events if e.event_id == correction_id)
    parked = rows(
        effects, "posting", "SELECT status, error_class FROM parked_event WHERE event_id = %s", (correction_id,)
    )
    assert parked == [("dead", "original_missing")]
    posted = rows(
        effects, "posting", "SELECT revision FROM posting WHERE stay_id = %s ORDER BY revision", (correction.stay_id,)
    )
    assert posted == [(1,)], "the original posted; the correction's difference is still missing until a replay"
    assert credits_for(effects, [correction]) == {}


def test_s13_skewed_events_post_normally(effects, tmp_path):
    built = trigger_then_reset(effects, "S13", tmp_path)
    ids = [e.event_id for e in built.manifest.events]
    assert len(rows(effects, "posting", "SELECT 1 FROM posting WHERE event_id = ANY(%s)", (ids,))) == len(ids)
    assert rows(effects, "posting", "SELECT 1 FROM parked_event WHERE event_id = ANY(%s)", (ids,)) == []
    assert all(e.clock_offset_seconds == plans.SKEW_SECONDS for e in built.manifest.events)


def test_s16_leaves_a_question_and_nothing_else(effects, tmp_path):
    built = trigger_then_reset(effects, "S16", tmp_path)
    (asked,) = built.manifest.affected
    question = rows(
        effects, "ops", "SELECT stay_id FROM member_question WHERE member_number = %s", (asked.member_number,)
    )
    assert question == [(asked.stay_id,)]
    for table in ("posting", "parked_event", "skipped_event"):
        assert rows(effects, "posting", f"SELECT 1 FROM {table} WHERE stay_id = %s", (asked.stay_id,)) == []
    assert rows(effects, "ledger", "SELECT 1 FROM credits WHERE stay_id = %s", (asked.stay_id,)) == []


def test_lag_is_readable_and_zero_once_the_pipeline_is_quiet(effects):
    assert effects.count("lag") == 0
    signals = effects.signals()
    assert signals["consumer_lag"] == 0 and signals["parked_open"] == 0
