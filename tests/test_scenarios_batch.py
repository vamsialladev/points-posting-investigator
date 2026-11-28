"""The slow scenarios on the real stack, one at a time: S03, S04, S06 to S10, S12, S14, S15 (both pairs), S17, S18.

Each test triggers a scenario against the containerised services, checks the evidence the pre-registered catalog
names while the fault is in place, then resets and checks the end state: every event posted, one ledger credit per
stay revision. **A reset always runs,** even when a check fails, so one failure doesn't leave the stack broken for
the next scenario.

These restart containers and take minutes, so they are marked `batch` and left out of the required CI job. They run
in the "Scenario batch" workflow (GitHub Actions) and with `scripts\\test_integration.ps1 --batch`. Manifests are
written to `.scenario-runs/batch/`.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from app.scenarios import catalog, plans, run, steps
from app.scenarios.executor import Executor
from tests.scenario_helpers import capture, credits_for, free_run, rows, started

pytestmark = [pytest.mark.postgres, pytest.mark.kafka, pytest.mark.batch]
MANIFESTS = run.RUNS_DIR / "batch"
OPEN = ("pending", "in_flight")
READERS: dict[str, object] = {}


@pytest.fixture(autouse=True)
def _read_only_logins(evidence_readers):
    READERS["stack"] = evidence_readers


def phase(effects, name: str, built: steps.Plan) -> None:
    manifest = built.manifest
    said: list[str] = []
    ok = run.execute(name, manifest.scenario, manifest.run, manifest.pair, effects, directory=MANIFESTS,
                     say=said.append, executor=Executor(effects, poll_seconds=0.5))  # fmt: skip
    print("\n".join(said))  # shown with -s, and in the failure report
    assert ok, "\n".join(said)


@contextmanager
def triggered(effects, scenario: str, pair: str | None = None) -> Iterator[steps.Plan]:
    """Trigger, take a read-only evidence snapshot (kept for the workflow to upload), hand over for the checks made
    while the fault is in place, and always reset afterwards."""
    built = plans.plan(scenario, free_run(effects, scenario), pair)
    name = f"{scenario}{'-' + pair if pair else ''}-run{built.manifest.run}"
    since = started()
    try:
        phase(effects, "trigger", built)
        capture(READERS["stack"], name, since)
        yield built
    finally:
        phase(effects, "reset", built)


def thread_dump(service: str) -> str:
    """Ask a stack service for every thread's stack (SIGUSR1, faulthandler) and return what it wrote. Diagnostic
    only: it never fails a test, and says so when the dump can't be taken."""
    compose = ["docker", "compose", "--profile", "core"]
    try:
        subprocess.run([*compose, "kill", "-s", "SIGUSR1", service], cwd=run.ROOT, capture_output=True, timeout=30)
        time.sleep(1.0)
        logs = subprocess.run(
            [*compose, "logs", "--no-log-prefix", "--tail", "200", service],
            cwd=run.ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"thread dump of {service}: not taken ({type(exc).__name__})"
    lines = (logs.stdout + logs.stderr).splitlines()
    starts = [n for n, line in enumerate(lines) if line.startswith(("Thread 0x", "Current thread 0x"))]
    if not starts:
        return f"thread dump of {service}: no stack found in its last 200 log lines"
    # The service's own console lines just before the dump (its ledger request lines left out): what it logged,
    # whether or not the log handler stored it.
    before = [line for line in lines[: starts[0]] if "HTTP Request:" not in line and "rdkafka" not in line][-30:]
    return (
        f"console of {service} before the dump:\n"
        + "\n".join("  " + line[:170] for line in before)
        + f"\nthread dump of {service}:\n"
        + "\n".join("  " + line[:170] for line in lines[starts[0] :][:60])
    )


def ids(events) -> list[str]:
    return [event.event_id for event in events]


def posted_ids(effects, events) -> set[str]:
    return {
        r[0] for r in rows(effects, "posting", "SELECT event_id FROM posting WHERE event_id = ANY(%s)", (ids(events),))
    }


def parked(effects, events) -> list[tuple]:
    """(event_id, status, error_class, attempts, transient_failures) of the events that were ever parked."""
    return rows(
        effects,
        "posting",
        "SELECT event_id, status, error_class, attempts, transient_failures FROM parked_event"
        " WHERE event_id = ANY(%s) ORDER BY id",
        (ids(events),),
    )


def assert_all_posted_and_credited_once(effects, events) -> None:
    assert posted_ids(effects, events) == set(ids(events)), "every event posted"
    assert credits_for(effects, events) == {f"{e.stay_id}:{e.revision}": 1 for e in events}, "one credit each"
    assert [row for row in parked(effects, events) if row[1] != "done"] == [], "nothing is still parked or dead"


def assert_parked_as_transient(effects, events, error_class: str) -> None:
    """At least one event is parked open with this class; an outage is never counted toward dead-lettering."""
    failing = [row for row in parked(effects, events) if row[2] == error_class]
    assert failing, f"no event parked as {error_class}: {parked(effects, events)}"
    for _event_id, status, _class, attempts, transient in failing:
        assert status in OPEN and attempts == 0 and transient >= 1
    assert not set(ids(events)) & effects.kafka.dead_letter_event_ids(), "a transient failure never dead-letters"


def test_s03_a_slow_ledger_parks_events_as_timeouts_and_they_post_after_the_reset(effects):
    with triggered(effects, "S03") as built:
        assert_parked_as_transient(effects, built.manifest.events, "ledger_timeout_not_found")
        assert rows(effects, "ops", "SELECT 1 FROM change_event WHERE changed_at > now() - interval '10 minutes'") == []
    assert_all_posted_and_credited_once(effects, built.manifest.events)


def test_s04_a_rate_limited_ledger_parks_events_and_they_post_after_the_reset(effects):
    with triggered(effects, "S04") as built:
        assert_parked_as_transient(effects, built.manifest.events, "ledger_rate_limited")
    assert_all_posted_and_credited_once(effects, built.manifest.events)


def test_s06_a_posting_restart_mid_stream_loses_nothing_and_credits_nothing_twice(effects):
    with triggered(effects, "S06") as built:
        pass
    assert_all_posted_and_credited_once(effects, built.manifest.events)
    started = rows(
        effects,
        "ops",
        "SELECT count(*) FROM log_event WHERE service = 'posting' AND message = 'posting service started'"
        " AND logged_at > now() - interval '10 minutes'",
    )
    assert started[0][0] >= 1, "the restart left a start-up line in the stored logs"


def test_s07_a_posting_database_outage_makes_partitions_wait_and_nothing_is_lost(effects):
    """The first version asserted "the ledger credited a stay with no posting row yet". It passed twice and failed
    the third time: the service reads its database before the ledger call, so that state exists only for an event
    caught mid-flight when the login is cut (at most one per partition, often none). It is now counted and bounded,
    and the checks below are the ones that always hold (verification log, M3 Phase 2)."""
    partitions = 3
    with triggered(effects, "S07") as built:
        events = built.manifest.events
        posted, credited = posted_ids(effects, events), credits_for(effects, events)
        assert len(posted) < len(events), "some events could not be posted while the role could not log in"
        assert effects.count("lag") >= 1, "the partitions wait: the group falls behind"
        assert parked(effects, events) == [], "a database failure is not parked: the partition waits"
        in_flight = [e for e in events if e.event_id not in posted and f"{e.stay_id}:1" in credited]
        print(f"S07: {len(posted)}/{len(events)} posted, {len(in_flight)} credited without a posting row yet")
        assert len(in_flight) <= partitions, "at most one event per partition was past its reads when the cut came"
        assert len(credited) <= len(posted) + partitions, "no event was credited after the database went away"
        # The retry lines, checked at once, with no wait. This check failed in two runs while the service was doing
        # the right thing: its log handler lost single lines (a one-row insert asked for RETURNING, which the
        # insert-only role may not do). By now the outage is at least 10 s old and the service has retried about
        # five times with its growing wait, so three stored lines is a floor (verification log, M3 Phase 2).
        stored = rows(
            effects,
            "ops",
            "SELECT to_char(logged_at, 'HH24:MI:SS.MS'), level, message FROM log_event"
            " WHERE service = 'posting' AND logged_at > now() - interval '90 seconds' ORDER BY id",
        )
        retries = [line for line in stored if line[1] == "WARNING" and "in place after DatabaseFailure" in line[2]]
        print(f"S07: {len(stored)} stored posting lines in the last 90 s; {len(retries)} are DatabaseFailure retries")
        if len(retries) < 3:  # only then: what the service logged on its console, and where its threads are
            print(thread_dump("posting"))
            for at, level, message in stored[-40:]:
                print(f"  {at} {level} {message[:140]}")
        assert len(retries) >= 3, "the outage left the service's retry lines in the stored logs"
    assert_all_posted_and_credited_once(effects, built.manifest.events)


def test_s08_an_expired_credential_parks_events_and_nothing_is_credited_until_it_is_renewed(effects):
    with triggered(effects, "S08") as built:
        assert_parked_as_transient(effects, built.manifest.events, "ledger_unauthorized")
        assert credits_for(effects, built.manifest.events) == {}
    assert_all_posted_and_credited_once(effects, built.manifest.events)


def test_s09_a_slow_ledger_builds_lag_with_no_errors(effects):
    with triggered(effects, "S09") as built:  # the trigger itself waits until the lag is at least 10
        assert parked(effects, built.manifest.events) == [], "slow, not failing: nothing is parked"
    assert_all_posted_and_credited_once(effects, built.manifest.events)
    assert effects.count("lag") == 0


def test_s10_a_stopped_relay_leaves_postings_unpublished_until_it_starts_again(effects):
    with triggered(effects, "S10") as built:  # the trigger waits until 10 outbox rows are unpublished
        events = built.manifest.events
        assert posted_ids(effects, events) == set(ids(events)) and len(credits_for(effects, events)) == len(events)
        assert effects.count("outbox_unpublished") >= len(events)
    assert effects.count("outbox_unpublished") == 0
    assert_all_posted_and_credited_once(effects, built.manifest.events)


def test_s12_a_lowered_timeout_parks_events_with_a_change_record_just_before(effects):
    def changes() -> list[tuple]:
        return rows(
            effects,
            "ops",
            "SELECT old_value, new_value FROM change_event WHERE service = 'posting' AND setting = %s"
            " AND changed_at > now() - interval '15 minutes' ORDER BY id",
            (plans.LEDGER_TIMEOUT_SETTING,),
        )

    before = len(changes())
    with triggered(effects, "S12") as built:
        assert_parked_as_transient(effects, built.manifest.events, "ledger_timeout_not_found")
        assert changes()[before:] == [(plans.LEDGER_TIMEOUT_DEFAULT, plans.LEDGER_TIMEOUT_BROKEN)]
    assert changes()[before:] == [
        (plans.LEDGER_TIMEOUT_DEFAULT, plans.LEDGER_TIMEOUT_BROKEN),
        (plans.LEDGER_TIMEOUT_BROKEN, plans.LEDGER_TIMEOUT_DEFAULT),
    ]
    assert_all_posted_and_credited_once(effects, built.manifest.events)


def test_s14_a_rebalance_storm_loses_nothing_and_credits_nothing_twice(effects):
    def rebalance_lines() -> int:
        found = rows(
            effects,
            "ops",
            "SELECT count(*) FROM log_event WHERE service = 'posting'"
            " AND (message LIKE 'partitions revoked:%%' OR message LIKE 'partitions assigned:%%')"
            " AND logged_at > now() - interval '3 minutes'",
        )
        return int(found[0][0])

    before = rebalance_lines()
    with triggered(effects, "S14") as built:
        flaps = next(s.times for s in built.trigger if isinstance(s, steps.GroupFlap))
        # Each join and each leave moves the posting service's partitions at least once. Half of that is asserted,
        # so a rebalance that covers two changes at once doesn't fail the test.
        assert rebalance_lines() - before >= flaps, "the storm left assigned and revoked lines in the stored logs"
    assert_all_posted_and_credited_once(effects, built.manifest.events)


def test_s15_pair_a_rate_limit_and_stopped_relay_at_once(effects):
    with triggered(effects, "S15", "A") as built:
        events = built.manifest.events
        assert [row for row in parked(effects, events) if row[2] == "ledger_rate_limited" and row[1] in OPEN]
        assert effects.count("outbox_unpublished") >= 10
    assert_all_posted_and_credited_once(effects, built.manifest.events)
    assert built.manifest.root_causes == catalog.S15_PAIRS["A"].root_causes


def test_s15_pair_b_correction_before_original_and_a_schema_break_at_once(effects):
    with triggered(effects, "S15", "B") as built:
        pass
    events = built.manifest.events
    (correction_id,) = built.manifest.replay_event_ids
    bad = [e for e in events if e.kind != steps.VALID]
    dead = effects.kafka.dead_letter_event_ids()
    assert correction_id in dead and set(ids(bad)) <= dead
    assert [(r[1], r[2]) for r in parked(effects, events) if r[0] == correction_id] == [("dead", "original_missing")]
    expected_posted = [e for e in events if e.kind == steps.VALID and e.event_id != correction_id]
    assert posted_ids(effects, events) == set(ids(expected_posted))
    assert credits_for(effects, events) == {f"{e.stay_id}:{e.revision}": 1 for e in expected_posted}


def test_s17_planted_text_is_stored_as_data_and_the_pipeline_behaves_as_in_s05(effects):
    def runbook_lines(tag: str) -> list[tuple]:
        return rows(effects, "ops", "SELECT body FROM runbook_section WHERE tag = %s", (tag,))

    with triggered(effects, "S17") as built:
        tag = next(s.tag for s in built.trigger if isinstance(s, steps.PlantRunbook))
        assert runbook_lines(tag) == [(catalog.INJECTION_RUNBOOK_LINE,)]
    assert runbook_lines(tag) == [], "the reset removed exactly the planted line"
    events = built.manifest.events
    poison = max(events, key=lambda e: e.room_rate_cents)
    assert poison.correlation_id == catalog.INJECTION_CORRELATION_ID
    assert [(r[1], r[2], r[3]) for r in parked(effects, [poison])] == [("dead", "ledger_rejected_422", 5)]
    others = [e for e in events if e is not poison]
    assert posted_ids(effects, events) == set(ids(others))
    assert credits_for(effects, events) == {f"{e.stay_id}:1": 1 for e in others}
    stored = rows(
        effects,
        "ops",
        "SELECT correlation_id FROM log_event WHERE message = %s AND logged_at > now() - interval '15 minutes'",
        (catalog.INJECTION_LOG_MESSAGE,),
    )
    assert (catalog.INJECTION_CORRELATION_ID,) in stored


def test_s18_the_postings_dropped_alert_fires_while_nothing_else_is_wrong(effects):
    with triggered(effects, "S18") as built:  # the trigger fails unless the alert fired
        latest = rows(
            effects,
            "ops",
            "SELECT rule, state FROM alert_evaluation WHERE evaluated_at > now() - interval '30 seconds' ORDER BY id",
        )
        states = dict(latest)
        assert states[plans.ALERT_POSTINGS_DROPPED] == "firing"
        quiet = {rule: state for rule, state in states.items() if rule != plans.ALERT_POSTINGS_DROPPED}
        assert quiet and set(quiet.values()) == {"quiet"}, f"only the noisy rule fired: {states}"
    assert_all_posted_and_credited_once(effects, built.manifest.events)


def test_after_the_whole_batch_the_ledger_holds_no_key_twice_and_the_pipeline_is_quiet(effects):
    duplicates = rows(effects, "ledger", "SELECT idempotency_key FROM credits GROUP BY 1 HAVING count(*) > 1")
    assert duplicates == []
    assert rows(effects, "ledger", "SELECT count(*) FROM credits")[0][0] > 100, "the batch did credit stays"
    signals = effects.signals()
    assert (signals["consumer_lag"], signals["parked_open"], signals["outbox_unpublished"]) == (0, 0, 0)
