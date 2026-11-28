"""The 18 committed dev snapshots (benchmarks/snapshots/dev/): complete, readable, and each one its own incident.

A snapshot is evidence as GitHub Actions read it on a real stack. These tests don't check what a scenario did (the
real-stack scenario tests do that); they check that a file is a usable, uncontaminated dev incident.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime

import pytest

from app.evidence import dev
from app.evidence.model import KINDS
from app.scenarios import catalog, plans

SCENARIOS = sorted(catalog.SCENARIOS)
MEMBER_FIELDS = ("member_number", "key")


def block_members(scenario: str) -> set[str]:
    block = plans.Block(scenario, dev.DEV_RUN)
    return {block.member(j) for j in range(block.members)}


def test_there_is_exactly_one_file_per_scenario_and_nothing_else():
    assert sorted(p.name for p in dev.FOLDER.glob("*")) == sorted(f"{dev.name(s)}.json" for s in SCENARIOS)
    assert len(SCENARIOS) == 18


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_a_dev_snapshot_loads_is_complete_and_cites_each_item_once(scenario):
    snapshot = dev.load(scenario)
    assert snapshot.truncated == (), "no read hit its limit, so nothing was left out"
    assert snapshot.items and {item.kind for item in snapshot.items} <= set(KINDS)
    assert len(snapshot.ids()) == len(snapshot.items)
    assert snapshot.since < snapshot.taken_at
    assert all(item.at is None or item.at >= snapshot.since for item in snapshot.items if item.kind != "lag")
    assert len(snapshot.of("lag")) == 3, "one lag reading per partition of the input topic"


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_a_dev_snapshot_holds_only_its_own_scenarios_members(scenario):
    """Scenarios run one after another on one stack. If the one before were still finishing, its rows would sit in
    this window and the incident would have two causes. Every member named here must be from this scenario's block."""
    own = block_members(scenario)
    strangers = sorted(
        {
            f"{item.id}: {item.data[field]}"
            for item in dev.load(scenario).items
            for field in MEMBER_FIELDS
            if isinstance(item.data.get(field), str) and item.data[field].startswith("GR-")
            if item.data[field] not in own
        }
    )
    assert strangers == []


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_the_manifests_events_are_what_the_snapshot_saw(scenario):
    """The ground truth comes from the trigger's plan, which is pure code: the same plan the workflow ran."""
    built = plans.plan(scenario, dev.DEV_RUN, dev.DEV_PAIR.get(scenario))
    sent = {event.event_id for event in built.manifest.events}
    seen = {item.data.get("event_id") for item in dev.load(scenario).items if item.kind in ("event", "dead_letter")}
    assert sent <= seen, "every event the trigger sent is on a topic in the window"


def classes(snapshot, kind: str) -> set[str]:
    return {item.data["error_class"] for item in snapshot.of(kind) if item.data.get("error_class")}


def open_parked(snapshot) -> list:
    return [item for item in snapshot.of("parked") if item.data["status"] in ("pending", "in_flight")]


def pending_outbox_ages(snapshot) -> list[float]:
    taken = datetime.fromisoformat(snapshot.taken_at)
    waiting = [item for item in snapshot.of("outbox") if item.data["status"] == "pending"]
    return sorted((taken - datetime.fromisoformat(item.at)).total_seconds() for item in waiting)


def on_topic(snapshot, topic: str) -> list:
    return [item for item in snapshot.of("event") if item.data["topic"] == topic]


def messages(snapshot) -> list[str]:
    return [item.data["message"] for item in snapshot.of("log")]


def total_lag(snapshot) -> int:
    return sum(item.data["lag"] for item in snapshot.of("lag"))


def poison(s) -> bool:
    dead = [i for i in s.of("parked") if i.data["status"] == "dead"]
    return (
        classes(s, "dead_letter") == {"ledger_rejected_422"}
        and [(i.data["attempts"], i.data["error_class"]) for i in dead] == [(5, "ledger_rejected_422")]
        and [i.data["attempt"] for i in s.of("dead_letter")] == ["5"]
    )


def s02(s) -> bool:
    offsets = Counter(i.data["event_id"] for i in on_topic(s, "stay.checked_out"))
    stays = Counter((i.data["stay_id"], i.data["revision"]) for i in s.of("posting"))
    return max(offsets.values()) >= 2 and set(stays.values()) == {1} and len(s.of("credit")) == len(stays)


def s06(s) -> bool:
    lines = messages(s)
    started = lines.index("posting service started")
    return any(line.startswith("partitions assigned") for line in lines[started:]) and not s.of("parked")


def s11(s) -> bool:
    (dead,) = s.of("dead_letter")
    original = [i for i in s.of("posting") if i.data["stay_id"] == dead.data["stay_id"] and i.data["revision"] == 1]
    return (
        (dead.data["error_class"], dead.data["revision"]) == ("original_missing", 2)
        and len(original) == 1
        and original[0].at > dead.at
    )


def s12(s) -> bool:
    (change,) = s.of("change")
    failures = [i.data["first_failed_at"] for i in s.of("parked") if i.data["error_class"]]
    return (
        (change.data["service"], change.data["setting"]) == ("posting", plans.LEDGER_TIMEOUT_SETTING)
        and classes(s, "parked") == {"ledger_timeout_not_found"}
        and change.at < min(failures)
    )


def s13(s) -> bool:
    skews = [i.data["occurred_minus_broker_seconds"] for i in on_topic(s, "stay.checked_out")]
    return (
        all(abs(skew - plans.SKEW_SECONDS) < 120 for skew in skews)
        and len(s.of("posting")) == len(skews) > 0
        and not s.of("parked")
        and not s.of("dead_letter")
    )


def s16(s) -> bool:
    (asked,) = s.of("question")
    stay = asked.data["stay_id"]
    return not [i for i in s.items if i.kind != "question" and i.data.get("stay_id") == stay]


def s18(s) -> bool:
    firing = [i.data["rule"] for i in s.of("alert") if i.data["state"] == "firing"]
    quiet = total_lag(s) == 0 and not open_parked(s) and not pending_outbox_ages(s) and not s.of("dead_letter")
    return firing == [plans.ALERT_POSTINGS_DROPPED] and quiet


STORED_EVIDENCE = {
    "S01": lambda s: (
        classes(s, "dead_letter") == {"schema", "schema_version"}
        and {i.data["attempt"] for i in s.of("dead_letter")} == {"1"}
        and not s.of("parked")
    ),
    "S02": s02,
    "S03": lambda s: (
        classes(s, "parked") == {"ledger_timeout_not_found"}
        and all(i.data["transient_failures"] > 0 for i in open_parked(s))
        and not s.of("change")
        and not s.of("dead_letter")
    ),
    "S04": lambda s: classes(s, "parked") == {"ledger_rate_limited"} and not s.of("dead_letter"),
    "S05": poison,
    "S06": s06,
    "S07": lambda s: (
        len(on_topic(s, "stay.checked_out")) > len(s.of("posting"))
        and total_lag(s) >= 1
        and sum("in place after DatabaseFailure" in line for line in messages(s)) >= 3
        and not s.of("parked")
    ),
    "S08": lambda s: classes(s, "parked") == {"ledger_unauthorized"} and not s.of("credit"),
    "S09": lambda s: total_lag(s) >= 10 and not s.of("parked") and not s.of("dead_letter"),
    "S10": lambda s: (
        len(pending_outbox_ages(s)) >= 5
        and pending_outbox_ages(s)[-1] >= 10
        and not on_topic(s, "points.posted")
        and len(s.of("posting")) == len(s.of("credit")) > 0
    ),
    "S11": s11,
    "S12": s12,
    "S13": s13,
    "S14": lambda s: (
        sum(line.startswith("partitions revoked") for line in messages(s)) >= 3
        and sum(line.startswith("partitions assigned") for line in messages(s)) >= 3
        and not s.of("parked")
    ),
    "S15": lambda s: (
        classes(s, "parked") == {"ledger_rate_limited"}
        and len(pending_outbox_ages(s)) >= 5
        and pending_outbox_ages(s)[-1] >= 10
    ),
    "S16": s16,
    "S17": lambda s: (
        poison(s)
        and catalog.INJECTION_LOG_MESSAGE in messages(s)
        and {i.data["correlation_id"] for i in s.of("dead_letter")} == {catalog.INJECTION_CORRELATION_ID}
    ),
    "S18": s18,
}


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_a_dev_snapshot_holds_the_stored_evidence_its_catalog_entry_names(scenario):
    """docs/failure-catalog.md, each entry's "Evidence" line, as far as it is stored (metrics are not: they come
    with Milestone 4). If a trigger ends before its evidence exists, the snapshot is of half an incident: S06 once
    had no "started" line and S10's unpublished rows were 1.8 s old (verification log M3 Phase 3 #9 and #10)."""
    assert set(STORED_EVIDENCE) == set(SCENARIOS)
    assert STORED_EVIDENCE[scenario](dev.load(scenario))


def test_no_file_holds_a_login_or_a_key_shape():
    for scenario in SCENARIOS:
        text = dev.path(scenario).read_text(encoding="utf-8")
        json.loads(text)
        for shape in ("sk-ant-", "PASSWORD", "password=", "Bearer ", "postgresql+psycopg://"):
            assert shape not in text, f"{dev.name(scenario)} contains {shape!r}"


def test_an_unknown_scenario_is_refused():
    with pytest.raises(ValueError):
        dev.name("S99")
