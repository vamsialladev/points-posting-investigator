"""The scenario executor's own logic, offline: pacing, background sends, waits that fail at their timeout, alerts."""

from __future__ import annotations

import threading

import pytest

from app.scenarios import catalog, plans, steps
from app.scenarios.executor import Executor, StepFailed


class Clock:
    """Time that only moves when something sleeps, so nothing here waits for real."""

    def __init__(self) -> None:
        self.now, self._lock = 0.0, threading.Lock()

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        with self._lock:
            self.now += seconds


class Recorder:
    """Records every effect. `counts` and `states` script what the read-only conditions answer, call by call."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.calls: list[tuple] = []
        self.counts: dict[str, list[int]] = {}
        self.pending: dict[str, int] = {}  # condition -> polls until every event is in that state
        self.firing: list[str] = []
        self.fail_send_after: int | None = None
        self._lock = threading.Lock()

    def _note(self, *call: object) -> None:
        with self._lock:
            self.calls.append(call)

    def send(self, event: steps.EventSpec) -> None:
        sent = sum(1 for c in self.calls if c[0] == "send")
        if self.fail_send_after is not None and sent >= self.fail_send_after:
            raise ConnectionError("Kafka refused the event")
        self._note("send", event.event_id, self.clock())

    def ledger_control(self, step):
        self._note("ledger_control", step)

    def compose(self, step):
        self._note("compose", step.action, step.services)

    def role_login(self, step):
        self._note("role_login", step.role, step.allowed)

    def record_change(self, step):
        self._note("record_change", step.old, step.new)

    def record_question(self, step):
        self._note("record_question", step.member_number, step.stay_id)

    def plant_log(self, step):
        self._note("plant_log", step.message)

    def plant_runbook(self, step):
        self._note("plant_runbook", step.tag)

    def remove_runbook(self, step):
        self._note("remove_runbook", step.tag)

    def join_group(self, group):
        self._note("join", group, self.clock())
        return lambda: self._note("leave", group, self.clock())

    def count(self, condition):
        values = self.counts.get(condition, [0])
        value = values.pop(0) if len(values) > 1 else values[0]
        self._note("count", condition, value)
        return value

    def missing(self, condition, event_ids):
        left = self.pending.get(condition, 0)
        self.pending[condition] = max(left - 1, 0)
        self._note("missing", condition, len(event_ids))
        return event_ids if left > 0 else ()

    def firing_alerts(self):
        return list(self.firing)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def effects(clock) -> Recorder:
    return Recorder(clock)


def run(effects, clock, plan_steps):
    return Executor(effects, clock, clock.sleep).run(tuple(plan_steps))


def events(n: int, **kwargs) -> tuple[steps.EventSpec, ...]:
    block = plans.Block("S02", 0)
    return tuple(block.event(i, i, **kwargs) for i in range(n))


def test_events_are_sent_in_order_at_the_rate_and_copies_are_sent_again(effects, clock):
    batch = events(3, copies=2)
    results = run(effects, clock, [steps.SendEvents(batch, rate=4)])
    sends = [c for c in effects.calls if c[0] == "send"]
    assert [c[1] for c in sends] == [e.event_id for e in batch for _ in range(2)]
    assert [c[2] for c in sends] == [0.0, 0.25, 0.5, 0.75, 1.0, 1.25]
    assert results[0].detail == "sent 6"


def test_a_background_send_overlaps_the_next_steps_and_join_waits_for_it(effects, clock):
    batch = events(5)
    run(
        effects,
        clock,
        [steps.SendEvents(batch, rate=100, background=True), steps.Compose("restart", ("posting",)), steps.JoinSends()],
    )
    kinds = [c[0] for c in effects.calls]
    assert kinds.count("send") == 5 and "compose" in kinds


def test_a_failed_background_send_is_reported_by_the_join(effects, clock):
    effects.fail_send_after = 2
    with pytest.raises(StepFailed, match=r"step 2 \(JoinSends\) failed: .*Kafka refused"):
        run(effects, clock, [steps.SendEvents(events(5), rate=100, background=True), steps.JoinSends()])


def test_a_failed_send_stops_the_run_and_names_the_step(effects, clock):
    effects.fail_send_after = 1
    with pytest.raises(StepFailed) as failed:
        run(
            effects,
            clock,
            [steps.LedgerControl(latency_ms=1), steps.SendEvents(events(3), rate=10), steps.Wait(1, "x")],
        )
    assert failed.value.index == 1 and "ConnectionError" in failed.value.reason
    assert clock() < 1, "the step after the failure never ran"


def test_a_background_send_that_is_never_joined_is_an_error(effects, clock):
    with pytest.raises(StepFailed, match="never joined"):
        run(effects, clock, [steps.SendEvents(events(2), rate=100, background=True)])
    assert [c[0] for c in effects.calls].count("send") == 2, "the sender was still joined, not left running"


def test_wait_for_polls_until_the_count_is_reached(effects, clock):
    effects.counts["parked_open"] = [0, 0, 3]
    (result,) = run(effects, clock, [steps.WaitFor("parked_open", at_least=1, timeout_seconds=30)])
    assert result.detail == "parked_open = 3" and clock() == 2.0  # two polls, one second apart


def test_wait_for_equals_waits_for_the_exact_value(effects, clock):
    effects.counts["lag"] = [40, 12, 0]
    (result,) = run(effects, clock, [steps.WaitFor("lag", equals=0, timeout_seconds=30)])
    assert result.detail == "lag = 0"


def test_wait_for_fails_at_its_timeout_and_says_what_it_saw(effects, clock):
    effects.counts["parked_open"] = [0]
    with pytest.raises(StepFailed, match=r"TimeoutError: after 5 s: parked_open = 0"):
        run(effects, clock, [steps.WaitFor("parked_open", at_least=1, timeout_seconds=5)])
    assert 5 <= clock() <= 6


def test_wait_for_events_waits_until_none_is_missing(effects, clock):
    effects.pending["dead_lettered"] = 2
    ids = ("e1", "e2")
    (result,) = run(effects, clock, [steps.WaitFor("dead_lettered", event_ids=ids, timeout_seconds=30)])
    assert result.detail == "0 of 2 not yet dead_lettered" and clock() == 2.0
    effects.pending["posted"] = 10**6
    with pytest.raises(StepFailed, match="2 of 2 not yet posted"):
        run(effects, clock, [steps.WaitFor("posted", event_ids=ids, timeout_seconds=3)])


def test_an_unknown_condition_is_refused(effects, clock):
    with pytest.raises(StepFailed, match="unknown condition"):
        run(effects, clock, [steps.WaitFor("ledger_balance", equals=0)])


def test_the_alert_step_fails_unless_the_expected_rule_fired(effects, clock):
    step = steps.EvaluateAlerts("postings_dropped")
    with pytest.raises(StepFailed, match="expected alert 'postings_dropped' to fire; firing: none"):
        run(effects, clock, [step])
    effects.firing = ["consumer_lag_high"]
    with pytest.raises(StepFailed, match="firing: \\['consumer_lag_high'\\]"):
        run(effects, clock, [step])
    effects.firing = ["postings_dropped"]
    assert run(effects, clock, [step])[0].detail == "firing: postings_dropped"


def test_a_group_flap_joins_and_leaves_the_given_number_of_times(effects, clock):
    run(effects, clock, [steps.GroupFlap("posting-service", times=3, hold_seconds=3, gap_seconds=2)])
    assert [(c[0], c[2]) for c in effects.calls] == [
        ("join", 0.0),
        ("leave", 3.0),
        ("join", 5.0),
        ("leave", 8.0),
        ("join", 10.0),
        ("leave", 13.0),
    ]


CASES = [(s, None) for s in catalog.SCENARIOS if s != "S15"] + [("S15", "A"), ("S15", "B")]


@pytest.mark.parametrize(("scenario", "pair"), CASES, ids=[f"{s}{p or ''}" for s, p in CASES])
def test_every_plan_runs_to_the_end_against_the_recorder(scenario, pair, effects, clock):
    """Every step type of every plan is handled. Counts are scripted so each wait is met: 'at least' sees a large
    number, and 'equals 0' sees 0 after it."""
    built = plans.plan(scenario, 0, pair)
    effects.firing = [plans.ALERT_POSTINGS_DROPPED]
    for phase in (built.trigger, built.reset):
        for condition in ("parked_open", "outbox_unpublished", "lag"):
            wants_many = any(isinstance(s, steps.WaitFor) and s.condition == condition and s.at_least for s in phase)
            effects.counts[condition] = [10**6] if wants_many else [0]
        results = run(effects, clock, phase)
        assert len(results) == len(phase)
    sent = [c[1] for c in effects.calls if c[0] == "send"]
    assert len(sent) == sum(e.copies for e in built.manifest.events)
    assert set(sent) == {e.event_id for e in built.manifest.events}
