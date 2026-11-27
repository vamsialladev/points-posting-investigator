"""Run a scenario plan, step by step. All side effects go through `Effects`, so this logic is tested offline.

- Events are paced at the plan's rate. A background send runs on a thread until `JoinSends`.
- `WaitFor` polls a read-only condition and **fails at its timeout**: a trigger that didn't produce its failure, or
  a reset that didn't get the pipeline quiet, is an error, never a silent success (standing rule 7).
- `EvaluateAlerts` fails unless the expected rule fired.
- A failed step stops the run. Whatever was already changed stays changed: run the reset.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from app.pipeline.loadgen import Pacer
from app.scenarios import steps
from app.scenarios.steps import (
    Compose,
    EvaluateAlerts,
    EventSpec,
    GroupFlap,
    JoinSends,
    LedgerControl,
    PlantLog,
    PlantRunbook,
    RecordChange,
    RecordQuestion,
    RemoveRunbook,
    RoleLogin,
    SendEvents,
    Step,
    Wait,
    WaitFor,
)

POLL_SECONDS = 1.0
EVENT_CONDITIONS = ("dead_lettered", "posted")  # true once every named event is in that state


class StepFailed(RuntimeError):
    def __init__(self, index: int, step: Step, reason: str) -> None:
        super().__init__(f"step {index + 1} ({type(step).__name__}) failed: {reason}")
        self.index, self.step, self.reason = index, step, reason


class Effects(Protocol):
    """Everything a plan can do to the stack. The real one is `stack.StackEffects`; tests use a recorder."""

    def send(self, event: EventSpec) -> None: ...
    def ledger_control(self, step: LedgerControl) -> None: ...
    def compose(self, step: Compose) -> None: ...
    def role_login(self, step: RoleLogin) -> None: ...
    def record_change(self, step: RecordChange) -> None: ...
    def record_question(self, step: RecordQuestion) -> None: ...
    def plant_log(self, step: PlantLog) -> None: ...
    def plant_runbook(self, step: PlantRunbook) -> None: ...
    def remove_runbook(self, step: RemoveRunbook) -> None: ...
    def join_group(self, group: str) -> Callable[[], None]: ...  # returns "leave"
    def count(self, condition: str) -> int: ...  # parked_open | outbox_unpublished | lag
    def missing(self, condition: str, event_ids: tuple[str, ...]) -> tuple[str, ...]: ...  # not yet in that state
    def firing_alerts(self) -> list[str]: ...


@dataclass(frozen=True)
class StepResult:
    step: str
    seconds: float
    detail: str = ""


class Executor:
    def __init__(
        self,
        effects: Effects,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        poll_seconds: float = POLL_SECONDS,
    ) -> None:
        self.effects, self.clock, self.sleep, self.poll_seconds = effects, clock, sleep, poll_seconds
        self._background: list[threading.Thread] = []
        self._background_errors: list[BaseException] = []

    def run(self, plan_steps: tuple[Step, ...]) -> list[StepResult]:
        results = []
        try:
            for index, step in enumerate(plan_steps):
                started = self.clock()
                try:
                    detail = self._run_step(step)
                except StepFailed:
                    raise
                except Exception as exc:
                    raise StepFailed(index, step, f"{type(exc).__name__}: {exc}") from exc
                results.append(StepResult(type(step).__name__, self.clock() - started, detail))
            if self._background:
                raise StepFailed(len(plan_steps) - 1, plan_steps[-1], "a background send was never joined")
        finally:
            self._join()  # never leave a sender running, whatever happened
        return results

    def _run_step(self, step: Step) -> str:
        effects = self.effects
        if isinstance(step, SendEvents):
            return self._send(step)
        if isinstance(step, JoinSends):
            return self._join(raise_errors=True)
        if isinstance(step, LedgerControl):
            effects.ledger_control(step)
        elif isinstance(step, Compose):
            effects.compose(step)
        elif isinstance(step, RoleLogin):
            effects.role_login(step)
        elif isinstance(step, RecordChange):
            effects.record_change(step)
        elif isinstance(step, RecordQuestion):
            effects.record_question(step)
        elif isinstance(step, PlantLog):
            effects.plant_log(step)
        elif isinstance(step, PlantRunbook):
            effects.plant_runbook(step)
        elif isinstance(step, RemoveRunbook):
            effects.remove_runbook(step)
        elif isinstance(step, GroupFlap):
            return self._flap(step)
        elif isinstance(step, Wait):
            self.sleep(step.seconds)
            return step.reason
        elif isinstance(step, WaitFor):
            return self._wait_for(step)
        elif isinstance(step, EvaluateAlerts):
            firing = effects.firing_alerts()
            if step.expect_firing not in firing:
                raise RuntimeError(f"expected alert {step.expect_firing!r} to fire; firing: {firing or 'none'}")
            return f"firing: {', '.join(firing)}"
        else:  # pragma: no cover (every Step type is handled above; a new one must be added here)
            raise TypeError(f"unknown step {type(step).__name__}")
        return ""

    def _send_all(self, step: SendEvents) -> int:
        pacer = Pacer(step.rate, self.clock, self.sleep)
        sent = 0
        for event in step.events:
            for _ in range(event.copies):
                pacer.wait()
                self.effects.send(event)
                sent += 1
        return sent

    def _send(self, step: SendEvents) -> str:
        if not step.background:
            return f"sent {self._send_all(step)}"

        def work() -> None:
            try:
                self._send_all(step)
            except BaseException as exc:  # reported by JoinSends, on the main thread
                self._background_errors.append(exc)

        thread = threading.Thread(target=work, name="scenario-send", daemon=True)
        self._background.append(thread)
        thread.start()
        return "sending in the background"

    def _join(self, raise_errors: bool = False) -> str:
        threads, self._background = self._background, []
        for thread in threads:
            thread.join()
        errors, self._background_errors = self._background_errors, []
        if errors and raise_errors:
            raise RuntimeError(f"a background send failed: {type(errors[0]).__name__}: {errors[0]}")
        return f"joined {len(threads)}"

    def _flap(self, step: GroupFlap) -> str:
        for _ in range(step.times):
            leave = self.effects.join_group(step.group)
            try:
                self.sleep(step.hold_seconds)
            finally:
                leave()
            self.sleep(step.gap_seconds)
        return f"joined and left {step.times} times"

    def _wait_for(self, step: WaitFor) -> str:
        if step.condition not in steps.CONDITIONS:
            raise ValueError(f"unknown condition {step.condition!r}")
        deadline = self.clock() + step.timeout_seconds
        while True:
            if step.condition in EVENT_CONDITIONS:
                missing = self.effects.missing(step.condition, step.event_ids)
                met, state = not missing, f"{len(missing)} of {len(step.event_ids)} not yet {step.condition}"
            else:
                value = self.effects.count(step.condition)
                met = value >= step.at_least if step.at_least is not None else value == step.equals
                state = f"{step.condition} = {value}"
            if met:
                return state
            if self.clock() >= deadline:
                raise TimeoutError(f"after {step.timeout_seconds:g} s: {state}")
            self.sleep(self.poll_seconds)
