"""Trigger or reset one scenario and keep its manifest (RFC-0002 Phase 2).

The manifest (`.scenario-runs/<scenario>[-pair]-run<N>.json`, git-ignored) holds the plan with its ground truth and
a record of each phase that ran: when, every step's result, and the error if a step failed. The ground truth in it
comes from the catalog, never from a model. Nothing here prints a setting's value.
"""

from __future__ import annotations

import dataclasses
import json
import os
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.scenarios import plans
from app.scenarios.executor import Effects, Executor, StepFailed
from app.scenarios.steps import Plan, Step

ROOT = Path(__file__).resolve().parent.parent.parent
RUNS_DIR = ROOT / ".scenario-runs"
PHASES = ("trigger", "reset")


def step_json(step: Step) -> dict[str, Any]:
    return {"step": type(step).__name__, **dataclasses.asdict(step)}


def plan_json(built: Plan) -> dict[str, Any]:
    return {
        "manifest": dataclasses.asdict(built.manifest),
        "trigger": [step_json(step) for step in built.trigger],
        "reset": [step_json(step) for step in built.reset],
    }


def manifest_path(scenario: str, run: int, pair: str | None, directory: Path = RUNS_DIR) -> Path:
    return directory / f"{scenario}{'-' + pair if pair else ''}-run{run}.json"


def execute(
    phase: str,
    scenario: str,
    run: int,
    pair: str | None,
    effects: Effects,
    *,
    directory: Path = RUNS_DIR,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    say: Callable[[str], None] = print,
    executor: Executor | None = None,
) -> bool:
    """Run one phase. Returns True when every step succeeded. The manifest is written either way."""
    if phase not in PHASES:
        raise ValueError(f"phase must be one of {PHASES}")
    built = plans.plan(scenario, run, pair)
    path = manifest_path(scenario, run, pair, directory)
    fresh = json.loads(json.dumps(plan_json(built), default=str))  # as it will read back: lists, not tuples
    document = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {**fresh, "phases": []}
    if document["manifest"] != fresh["manifest"]:
        raise RuntimeError(f"{path.name} was written by a different plan; move it away before running this one")
    plan_steps = built.trigger if phase == "trigger" else built.reset
    record: dict[str, Any] = {"phase": phase, "started_at": now().isoformat(), "ok": False, "steps": [], "error": None}
    say(f"{phase} {scenario}{' pair ' + pair if pair else ''} run {run}: {len(plan_steps)} step(s)")
    try:
        results = (executor or Executor(effects)).run(plan_steps)
        record["steps"] = [dataclasses.asdict(result) for result in results]
        record["ok"] = True
    except StepFailed as failed:
        record["error"] = str(failed)
        say(f"FAILED: {failed}")
        if phase == "trigger":
            say("Whatever the trigger already changed is still changed: run the reset.")
    record["finished_at"] = now().isoformat()
    document["phases"].append(record)
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")
    for result in record["steps"]:
        say(f"  {result['step']:<15} {result['seconds']:7.1f} s  {result['detail']}")
    say(f"{'ok' if record['ok'] else 'NOT ok'}; manifest: {path.relative_to(directory.parent)}")
    return bool(record["ok"])


def stack_effects(env: Mapping[str, str] | None = None) -> Effects:
    """The real effects, for the local stack. Reads `.env` in this process; prints nothing from it."""
    import httpx
    import psycopg
    from dotenv import load_dotenv
    from sqlalchemy.engine import make_url

    from app.db.bootstrap import conninfo
    from app.db.roles import Database
    from app.ops import alerts
    from app.scenarios import kafka_io, stack

    if env is None:
        load_dotenv(ROOT / ".env", override=False)
        env = os.environ
    stack.guard(env)
    admin = make_url(env["DATABASE_URL"])
    prefix = env.get("DB_PREFIX", "")
    ledger_url = env["LEDGER_API_URL"].replace("://localhost", "://127.0.0.1")
    token = env.get("LEDGER_API_TOKEN", "")

    def connect(base: str) -> AbstractContextManager[Any]:
        database = Database(base, prefix).name if base else None
        return psycopg.connect(**conninfo(admin, database), autocommit=True)

    def post_control(body: dict[str, Any]) -> int:
        reply = httpx.post(
            f"{ledger_url}/control/settings", json=body, headers={"Authorization": f"Bearer {token}"}, timeout=10
        )
        return reply.status_code

    return stack.StackEffects(
        kafka=kafka_io.build(env["KAFKA_BOOTSTRAP_SERVERS"], env["SCHEMA_REGISTRY_URL"], plans.POSTING_GROUP),
        connect=connect,
        post_control=post_control,
        run_command=lambda command, extra: stack.run_compose(command, extra, str(ROOT)),
        rules=alerts.load(),
    )
