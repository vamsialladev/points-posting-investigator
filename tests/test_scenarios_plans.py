"""The scenario plans are deterministic, don't collide across runs, and every reset undoes its trigger (FAIL-01..18).

Offline: the plans are data. Running them against the stack is tested with the executor.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, date, datetime, timedelta

import pytest

from app.pipeline import events as pipeline_events
from app.pipeline.producer import build_event
from app.scenarios import catalog, plans, steps
from app.scenarios.__main__ import main, plan_json

CASES = [(s, None) for s in catalog.SCENARIOS if s != "S15"] + [("S15", "A"), ("S15", "B")]
IDS = [f"{s}{p or ''}" for s, p in CASES]


def record_of(spec: steps.EventSpec) -> dict[str, object]:
    return build_event(
        member_number=spec.member_number,
        stay_id=spec.stay_id,
        check_in=date(2026, 11, 1),
        nights=spec.nights,
        room_rate_cents=spec.room_rate_cents,
        revision=spec.revision,
        event_id=spec.event_id,
        correlation_id=spec.correlation_id,
        occurred_at=datetime(2026, 11, 27, tzinfo=UTC) + timedelta(seconds=spec.clock_offset_seconds),
    )


def of_type(plan_steps: tuple[steps.Step, ...], kind: type) -> list:
    return [step for step in plan_steps if isinstance(step, kind)]


@pytest.mark.parametrize(("scenario", "pair"), CASES, ids=IDS)
def test_a_plan_is_the_same_every_time_and_carries_the_catalogs_ground_truth(scenario, pair):
    first, again = plans.plan(scenario, 3, pair), plans.plan(scenario, 3, pair)
    assert first == again
    assert (first.manifest.root_causes, first.manifest.recovery) == catalog.ground_truth(scenario, pair)
    assert first.trigger, "a trigger does something"
    json.dumps(plan_json(first))  # serialisable, for the manifest file and the dry run


@pytest.mark.parametrize(("scenario", "pair"), CASES, ids=IDS)
def test_two_runs_share_no_member_stay_or_event_id(scenario, pair):
    one, two = plans.plan(scenario, 0, pair).manifest, plans.plan(scenario, 1, pair).manifest
    for attribute in ("event_id", "member_number", "stay_id"):
        assert not {getattr(e, attribute) for e in one.events} & {getattr(e, attribute) for e in two.events}
    assert not {a.member_number for a in one.affected} & {a.member_number for a in two.affected}


@pytest.mark.parametrize(("scenario", "pair"), CASES, ids=IDS)
def test_every_event_sent_is_in_the_manifest_and_valid_events_pass_validation(scenario, pair):
    built = plans.plan(scenario, plans.MAX_RUN, pair)  # the last run still fits GR-##### and BR-/ML-####
    sent = [event for step in of_type(built.trigger, steps.SendEvents) for event in step.events]
    assert sorted(sent, key=lambda e: e.event_id) == sorted(built.manifest.events, key=lambda e: e.event_id)
    assert len({e.event_id for e in sent}) == len(sent), "one spec per event; duplicates are `copies`"
    assert of_type(built.reset, steps.SendEvents) == [], "a reset never sends events"
    for spec in sent:
        assert spec.kind in steps.EVENT_KINDS and spec.copies >= 1
        event = pipeline_events.validate(record_of(spec), {"schema_version": "1", "event_id": spec.event_id})
        assert pipeline_events.ledger_key(event) == f"{spec.stay_id}:{spec.revision}"
    keys = [(e.stay_id, e.revision) for e in sent]
    assert len(set(keys)) == len(keys), "no two events share a ledger key"


@pytest.mark.parametrize(("scenario", "pair"), CASES, ids=IDS)
def test_the_reset_puts_back_every_knob_the_trigger_moved(scenario, pair):
    built = plans.plan(scenario, 0, pair)
    moved: dict[str, object] = {}
    for step in built.trigger + built.reset:
        if isinstance(step, steps.LedgerControl):
            for name in ("latency_ms", "rate_per_sec", "burst"):
                if getattr(step, name) is not None:
                    moved[f"ledger.{name}"] = getattr(step, name)
            if step.expire_token or step.clear_token_expiry:
                moved["ledger.token_expired"] = step.expire_token
        elif isinstance(step, steps.Compose):
            for service in step.services:
                if step.action in ("stop", "start"):
                    moved[f"running.{service}"] = step.action == "start"
                for name, value in step.env:
                    moved[f"env.{service}.{name}"] = value
        elif isinstance(step, steps.RoleLogin):
            moved[f"login.{step.database}.{step.role}"] = step.allowed
        elif isinstance(step, steps.PlantRunbook):
            moved[f"runbook.{step.tag}"] = True
        elif isinstance(step, steps.RemoveRunbook):
            moved[f"runbook.{step.tag}"] = False
    defaults = {
        "ledger.latency_ms": 0,
        "ledger.rate_per_sec": plans.LEDGER_RATE_DEFAULT,
        "ledger.burst": plans.LEDGER_BURST_DEFAULT,
        "ledger.token_expired": False,
    }
    for knob, value in moved.items():
        if knob.startswith("env."):
            assert value == plans.LEDGER_TIMEOUT_DEFAULT, knob
        elif knob.startswith("runbook."):
            assert value is False, knob
        elif knob.startswith(("running.", "login.")):
            assert value is True, knob
        else:
            assert value == defaults[knob], knob
    assert of_type(built.trigger, steps.JoinSends) or not any(
        s.background for s in of_type(built.trigger, steps.SendEvents)
    )
    for wait in of_type(built.trigger + built.reset, steps.WaitFor):
        assert wait.condition in steps.CONDITIONS
        assert (wait.at_least is not None) + (wait.equals is not None) + bool(wait.event_ids) == 1, wait


def test_the_ledger_defaults_in_the_plans_are_the_ledgers_own():
    from app.ledger.core import LedgerSettings

    settings = LedgerSettings(token="x" * 12)
    assert (settings.rate_per_sec, settings.burst) == (plans.LEDGER_RATE_DEFAULT, plans.LEDGER_BURST_DEFAULT)
    assert settings.latency_ms == 0


def test_affected_members_follow_each_scenarios_rule():
    def affected(scenario: str, pair: str | None = None) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for item in plans.plan(scenario, 0, pair).manifest.affected:
            out.setdefault(item.effect, set()).add(item.member_number)
        return out

    for nobody in ("S02", "S06", "S07", "S09", "S10", "S14", "S18"):
        assert affected(nobody) == {}, nobody
    assert {k: len(v) for k, v in affected("S01").items()} == {steps.NOT_POSTED: 6}
    assert {k: len(v) for k, v in affected("S03").items()} == {steps.DELAYED: 4}
    assert {k: len(v) for k, v in affected("S05").items()} == {steps.NOT_POSTED: 1}
    assert {k: len(v) for k, v in affected("S11").items()} == {steps.CORRECTION_MISSING: 1}
    assert {k: len(v) for k, v in affected("S13").items()} == {steps.WRONG_DATES: 8}
    assert {k: len(v) for k, v in affected("S16").items()} == {steps.UNDECIDABLE: 1}
    assert affected("S17") == affected("S05")
    assert {k: len(v) for k, v in affected("S15", "B").items()} == {steps.CORRECTION_MISSING: 1, steps.NOT_POSTED: 6}
    for effect in (i.effect for s, p in CASES for i in plans.plan(s, 0, p).manifest.affected):
        assert effect in steps.EFFECTS


def test_s01_sends_unknown_versions_and_undecodable_bytes_among_valid_events():
    events = plans.plan("S01").manifest.events
    kinds = [e.kind for e in events]
    assert kinds.count(steps.UNKNOWN_SCHEMA_VERSION) == 3 and kinds.count(steps.UNDECODABLE) == 3
    assert kinds.count(steps.VALID) == 6
    dead = next(s for s in plans.plan("S01").trigger if isinstance(s, steps.WaitFor) and s.condition == "dead_lettered")
    assert set(dead.event_ids) == {e.event_id for e in events if e.kind != steps.VALID}


def test_s02_sends_every_event_more_than_once():
    assert sorted({e.copies for e in plans.plan("S02").manifest.events}) == [2, 3]
    assert all(e.copies == 1 for s, p in CASES if s != "S02" for e in plans.plan(s, 0, p).manifest.events)


def test_s05_poison_is_over_the_ledgers_limit_and_another_event_waits_behind_it():
    events = plans.plan("S05").manifest.events
    over = [
        e
        for e in events
        if pipeline_events.points_for(pipeline_events.validate(record_of(e), {"schema_version": "1"}))
        > plans.LEDGER_MAX_POINTS
    ]
    assert len(over) == 1
    behind = [e for e in events if e.member_number == over[0].member_number and e is not over[0]]
    assert len(behind) == 1 and events.index(behind[0]) > events.index(over[0])


def test_s11_sends_the_correction_first_and_the_replay_set_is_exactly_that_correction():
    built = plans.plan("S11")
    sends = of_type(built.trigger, steps.SendEvents)
    correction = sends[0].events[0]
    original = sends[1].events[0]
    assert len(sends[0].events) == 1 and correction.revision == 2 and original.revision == 1
    assert (correction.stay_id, correction.member_number) == (original.stay_id, original.member_number)
    assert built.manifest.replay_event_ids == (correction.event_id,)
    for scenario, pair in CASES:
        manifest = plans.plan(scenario, 0, pair).manifest
        assert bool(manifest.replay_event_ids) == (manifest.recovery == "dlq_replay"), scenario


def test_s12_records_the_change_before_it_breaks_the_timeout_and_never_touches_the_ledger():
    built = plans.plan("S12")
    assert isinstance(built.trigger[0], steps.RecordChange) and isinstance(built.trigger[1], steps.Compose)
    assert (built.trigger[0].old, built.trigger[0].new) == (plans.LEDGER_TIMEOUT_DEFAULT, plans.LEDGER_TIMEOUT_BROKEN)
    assert of_type(built.trigger + built.reset, steps.LedgerControl) == [], "the ledger itself is not slowed"
    revert = of_type(built.reset, steps.RecordChange)
    assert len(revert) == 1 and revert[0].new == plans.LEDGER_TIMEOUT_DEFAULT
    assert of_type(plans.plan("S03").trigger, steps.RecordChange) == [], "S03 has no change record"


def test_s13_events_are_hours_ahead_and_nothing_else_is_broken():
    built = plans.plan("S13")
    assert {e.clock_offset_seconds for e in built.manifest.events} == {plans.SKEW_SECONDS}
    assert all(isinstance(s, steps.SendEvents | steps.WaitFor) for s in built.trigger + built.reset)


def test_s16_sends_nothing_and_records_one_question():
    built = plans.plan("S16")
    assert built.manifest.events == () and len(built.trigger) == 1 and built.reset == ()
    assert isinstance(built.trigger[0], steps.RecordQuestion)


def test_s17_is_s05_with_the_three_planted_texts_and_the_reset_removes_the_runbook_line():
    base, poisoned = plans.plan("S05", 2), plans.plan("S17", 2)
    assert [dataclasses.replace(e, event_id="", correlation_id="") for e in poisoned.manifest.events] == [
        dataclasses.replace(e, event_id="", correlation_id="") for e in base.manifest.events
    ]
    assert [e.correlation_id for e in poisoned.manifest.events].count(catalog.INJECTION_CORRELATION_ID) == 1
    assert of_type(poisoned.trigger, steps.PlantLog)[0].message == catalog.INJECTION_LOG_MESSAGE
    planted = of_type(poisoned.trigger, steps.PlantRunbook)[0]
    assert planted.line == catalog.INJECTION_RUNBOOK_LINE
    assert of_type(poisoned.reset, steps.RemoveRunbook) == [steps.RemoveRunbook(planted.tag)]
    assert len(catalog.INJECTION_CORRELATION_ID) <= 100, "the ledger accepts correlation IDs up to 100 characters"


def test_s18_ends_by_evaluating_the_alert_after_everything_has_posted():
    trigger = plans.plan("S18").trigger
    assert trigger[-1] == steps.EvaluateAlerts(plans.ALERT_POSTINGS_DROPPED)
    assert isinstance(trigger[-2], steps.Wait) and trigger[1].condition == "posted"  # type: ignore[union-attr]


def test_a_compound_reset_restores_both_faults_before_it_waits():
    built = plans.plan("S15", 0, "A")
    kinds = [type(step) for step in built.reset]
    first_wait = kinds.index(steps.WaitFor)
    assert steps.Compose in kinds[:first_wait] and steps.LedgerControl in kinds[:first_wait]
    assert all(kind is steps.WaitFor for kind in kinds[first_wait:])
    parts = [plans.plan("S04").manifest, plans.plan("S10").manifest]
    assert len(built.manifest.events) == sum(len(p.events) for p in parts)
    members = [e.member_number for e in built.manifest.events]
    assert len(set(members)) == len(members), "the two parts use different members"


def test_runs_and_blocks_have_hard_edges():
    for run in (-1, plans.MAX_RUN + 1):
        with pytest.raises(ValueError):
            plans.plan("S05", run)
    block = plans.Block("S05", 0)
    for bad in (
        lambda: block.member(plans.MEMBERS_PER_RUN),
        lambda: block.stay(plans.STAYS_PER_RUN),
        lambda: block.member(-1),
    ):
        with pytest.raises(ValueError):
            bad()
    assert plans.Block("S05", plans.MAX_RUN).stay(plans.STAYS_PER_RUN - 1) <= "ML-9999"
    assert block.member(0) == "GR-30000" and block.stay(0) == "BR-0100" and block.stay(1) == "ML-0100"


def test_the_command_lists_and_shows_plans_and_refuses_a_bad_request(capsys):
    assert main(["list"]) == 0
    listed = capsys.readouterr().out
    assert listed.count("\n") == 18 and "S15" in listed and "pair B" in listed
    assert main(["plan", "S11", "--run", "4"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["manifest"]["recovery"] == "dlq_replay" and shown["trigger"][0]["step"] == "SendEvents"
    assert main(["plan", "S15"]) == 2
    assert "refused" in capsys.readouterr().err
