"""Scenarios triggered and reset on the real stack: the containerised posting service, retry worker, relay and ledger.

A fast subset runs here on every CI run: S01, S02, S05, S11, S13, S16. Each asserts the evidence the pre-registered
catalog says the scenario leaves, read from the databases and the dead-letter topic. The slower scenarios (restarts,
a database outage, a rebalance storm) are in tests/test_scenarios_batch.py, which the "Scenario batch" workflow runs.

The `effects` fixture and the helpers are in tests/scenario_helpers.py. These tests write synthetic rows into the
stack's own databases, in blocks of members and stays no other test or demo run uses.
"""

from __future__ import annotations

import pytest

from app.evidence.model import Snapshot
from app.pipeline import topics
from app.scenarios import plans, run, steps
from app.scenarios.executor import Executor
from tests.scenario_helpers import capture, credits_for, free_run, rows, started

pytestmark = [pytest.mark.postgres, pytest.mark.kafka]
READERS: dict[str, object] = {}
SNAPSHOTS: dict[str, Snapshot] = {}  # the evidence read after each trigger, as the read-only logins


@pytest.fixture(autouse=True)
def _read_only_logins(evidence_readers):
    READERS["stack"] = evidence_readers


def trigger_then_reset(effects, scenario: str, tmp_path) -> plans.Plan:
    """Trigger, take a read-only evidence snapshot (kept for the workflow to upload), then reset."""
    built = plans.plan(scenario, free_run(effects, scenario))
    number = built.manifest.run
    said: list[str] = []
    since = started()
    for phase in ("trigger", "reset"):
        ok = run.execute(phase, scenario, number, None, effects, directory=tmp_path, say=said.append,
                         executor=Executor(effects, poll_seconds=0.5))  # fmt: skip
        assert ok, "\n".join(said)
        if phase == "trigger":
            SNAPSHOTS[scenario] = capture(READERS["stack"], f"{scenario}-run{number}", since)
    return built


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
    # The same facts, as the read-only logins see them: this is what the rules and the investigator will cite.
    snapshot = SNAPSHOTS["S05"]
    dead = [i for i in snapshot.of("dead_letter") if i.data.get("event_id") == poison.event_id]
    assert len(dead) == 1 and dead[0].data["error_class"] == "ledger_rejected_422" and dead[0].data["attempt"] == "5"
    assert dead[0].data["key"] == poison.member_number
    parked_seen = [i for i in snapshot.of("parked") if i.data["event_id"] == poison.event_id]
    assert [(i.data["status"], i.data["attempts"]) for i in parked_seen] == [("dead", 5)]
    assert {i.data["stay_id"] for i in snapshot.of("credit")} >= {e.stay_id for e in others}
    assert poison.stay_id not in {i.data["stay_id"] for i in snapshot.of("credit")}
    assert snapshot.truncated == () and len(snapshot.ids()) == len(snapshot.items)


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


def test_s13_the_skew_shows_on_the_topic_and_only_there(effects, tmp_path):
    """The catalog's S13 evidence: an event's own `occurred_at` is hours ahead of the broker's timestamp for the same
    offset. Read as the `investigator` Kafka login. Events of other scenarios are the control: theirs agree."""
    _store, reader = READERS["stack"]
    skewed_ids = {e.event_id for number in range(plans.MAX_RUN + 1) for e in plans.plan("S13", number).manifest.events}
    found, _older_left_out = reader.messages(topics.CHECKED_OUT)
    decoded = [item for item in found if item.data.get("decoded")]
    skewed = [item for item in decoded if item.data["event_id"] in skewed_ids]
    control = [item for item in decoded if item.data["event_id"] not in skewed_ids]
    assert len(skewed) >= 8, "S13's events are on the topic (test_s13_skewed_events_post_normally ran before this)"
    assert len(control) >= 10, "and so are other scenarios' events, to compare with"
    for item in skewed:
        gap = item.data["occurred_minus_broker_seconds"]
        assert abs(gap - plans.SKEW_SECONDS) < 120, f"{item.id}: {gap} s"
        assert item.data["occurred_at"] > item.at, "the event claims to have happened after the broker received it"
    for item in control:
        assert abs(item.data["occurred_minus_broker_seconds"]) < 120, f"{item.id} is not skewed"
    # The stored rows show nothing: a posting row for a skewed event looks like any other.
    snapshot = SNAPSHOTS["S13"]
    posted = [i for i in snapshot.of("posting") if i.id.removeprefix("posting:") in skewed_ids]
    assert len(posted) >= 8 and all("occurred_at" not in i.data for i in posted)
    # None of S13's events was parked or dead-lettered. The window starts just before the trigger on a shared stack,
    # so it can hold the scenario before it (S11's dead letter lands seconds earlier): judge S13's own events only.
    aside = [i for i in (*snapshot.of("parked"), *snapshot.of("dead_letter")) if i.data.get("event_id") in skewed_ids]
    assert aside == []


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
