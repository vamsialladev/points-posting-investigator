"""The real side effects of a scenario plan, against the LOCAL stack only (RFC-0002 Phase 2, REC-09).

Every dependency is passed in (HTTP client, command runner, database connections, Kafka functions), so the logic
here is unit-tested with fakes; `kafka_io.py` holds the few lines that need a real broker.

Guards:
- **Local only.** `guard` refuses anything but loopback addresses, and refuses `PUBLIC_DEMO_MODE=true`.
- **The ledger's control endpoint can't credit.** It only changes latency, the rate limit and the token's expiry.
- The admin (superuser) connection is used to read state, to switch a runtime role's login (S07) and to write the
  scenario's own evidence rows (a change record, a member question, a planted log line and runbook line). It never
  writes a posting, an outbox row, a parked event or a credit.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlsplit

from app.db.roles import Database
from app.ops import alerts
from app.pipeline.producer import build_event
from app.scenarios import steps
from app.scenarios.steps import (
    Compose,
    EventSpec,
    LedgerControl,
    PlantLog,
    PlantRunbook,
    RecordChange,
    RecordQuestion,
    RemoveRunbook,
    RoleLogin,
)

LOOPBACK = ("127.0.0.1", "localhost", "::1")
WINDOW_SECONDS = 30
UNKNOWN_VERSION = "99"
COMPOSE = ("docker", "compose", "--profile", "core")
COMPOSE_ACTIONS = ("stop", "start", "restart", "up")
STACK_SERVICES = frozenset({"posting", "retry-worker", "relay", "ledger"})
OVERRIDABLE = frozenset({"LEDGER_TIMEOUT_SECONDS"})  # the only settings a scenario may override
QUESTION = "Where are my points for this stay?"
PLANTED_RUNBOOK = "poison-events"

SIGNALS_SQL = f"""
SELECT
  (SELECT count(*) FROM posting WHERE posted_at > now() - interval '{WINDOW_SECONDS} seconds'),
  (SELECT count(*) FROM posting WHERE posted_at <= now() - interval '{WINDOW_SECONDS} seconds'
                                  AND posted_at > now() - interval '{2 * WINDOW_SECONDS} seconds'),
  (SELECT count(*) FROM parked_event WHERE dead_at > now() - interval '{WINDOW_SECONDS} seconds'),
  (SELECT count(*) FROM parked_event WHERE status IN ('pending', 'in_flight')),
  (SELECT coalesce(extract(epoch FROM now() - min(parked_at)), 0) FROM parked_event
    WHERE status IN ('pending', 'in_flight')),
  (SELECT count(*) FROM outbox WHERE status IN ('pending', 'in_flight')),
  (SELECT coalesce(extract(epoch FROM now() - min(created_at)), 0) FROM outbox
    WHERE status IN ('pending', 'in_flight'))
"""  # noqa: S608 (only the fixed window constant is interpolated)
COUNT_SQL = {
    "parked_open": "SELECT count(*) FROM parked_event WHERE status IN ('pending', 'in_flight')",
    "outbox_unpublished": "SELECT count(*) FROM outbox WHERE status IN ('pending', 'in_flight')",
}


class NotLocal(RuntimeError):
    pass


def _host(value: str) -> str:
    return (urlsplit(value if "://" in value else f"//{value}").hostname or "").lower()


def guard(env: Mapping[str, str]) -> None:
    """Scenarios break things on purpose. Refuse unless every address is this machine and this isn't a public demo."""
    if env.get("PUBLIC_DEMO_MODE", "false").lower() == "true":
        raise NotLocal("PUBLIC_DEMO_MODE is true: scenarios never run against a public demo")
    for name in ("DATABASE_URL", "LEDGER_API_URL", "SCHEMA_REGISTRY_URL"):
        if _host(env.get(name, "")) not in LOOPBACK:
            raise NotLocal(f"{name} must point at this machine (127.0.0.1)")
    servers = [s for s in env.get("KAFKA_BOOTSTRAP_SERVERS", "").split(",") if s.strip()]
    if not servers or any(_host(server.strip()) not in LOOPBACK for server in servers):
        raise NotLocal("KAFKA_BOOTSTRAP_SERVERS must point at this machine (127.0.0.1)")


def record_for(event: EventSpec, now: datetime) -> dict[str, Any]:
    """The `stay.checked_out` record of a spec, stamped now (plus the spec's clock offset, S13)."""
    check_out: date = now.date()
    return build_event(
        member_number=event.member_number,
        stay_id=event.stay_id,
        check_in=check_out - timedelta(days=event.nights),
        nights=event.nights,
        room_rate_cents=event.room_rate_cents,
        revision=event.revision,
        event_id=event.event_id,
        correlation_id=event.correlation_id,
        occurred_at=now + timedelta(seconds=event.clock_offset_seconds),
    )


def control_body(step: LedgerControl, now: datetime) -> dict[str, Any]:
    body: dict[str, Any] = {}
    for name in ("latency_ms", "rate_per_sec", "burst"):
        if getattr(step, name) is not None:
            body[name] = getattr(step, name)
    if step.expire_token and step.clear_token_expiry:
        raise ValueError("a step can't both expire the token and clear its expiry")
    if step.expire_token:
        body["token_expires_at"] = (now - timedelta(hours=1)).isoformat()
    if step.clear_token_expiry:
        body["clear_token_expiry"] = True
    if not body:
        raise ValueError("a ledger control step must change something")
    return body


def compose_command(step: Compose) -> tuple[list[str], dict[str, str]]:
    """The exact command and the extra environment. Only known services, actions and settings are accepted."""
    if step.action not in COMPOSE_ACTIONS:
        raise ValueError(f"compose action {step.action!r} is not allowed")
    unknown = set(step.services) - STACK_SERVICES
    if unknown or not step.services:
        raise ValueError(f"not a stack service a scenario may touch: {sorted(unknown) or 'none given'}")
    extra = dict(step.env)
    if set(extra) - OVERRIDABLE:
        raise ValueError(f"a scenario may not override {sorted(set(extra) - OVERRIDABLE)}")
    if extra and step.action != "up":
        raise ValueError("settings can only change with `up`, which recreates the container")
    tail = ["up", "-d", "--no-deps", "--wait", "--wait-timeout", "120"] if step.action == "up" else [step.action]
    return [*COMPOSE, *tail, *step.services], extra


class Connection(Protocol):
    def execute(self, query: str, params: Sequence[Any] | None = None) -> Any: ...


Connect = Callable[[str], AbstractContextManager[Any]]  # database base name (posting | ops | "") -> a connection


@dataclass
class Kafka:
    """The broker-facing functions (`kafka_io.py` builds the real ones)."""

    send_valid: Callable[[dict[str, Any]], None]
    send_raw: Callable[[bytes, bytes, dict[str, str]], None]  # key, value, headers
    serialize: Callable[[dict[str, Any]], bytes]
    lag: Callable[[], int]
    dead_letter_event_ids: Callable[[], set[str]]
    join_group: Callable[[str], Callable[[], None]]


class StackEffects:
    def __init__(
        self,
        *,
        kafka: Kafka,
        connect: Connect,
        post_control: Callable[[dict[str, Any]], int],  # the ledger's control endpoint; returns the HTTP status
        run_command: Callable[[list[str], dict[str, str]], int],
        rules: tuple[alerts.Rule, ...],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.kafka, self.connect, self.post_control, self.run_command = kafka, connect, post_control, run_command
        self.rules, self.now = rules, now

    # ---- events ----
    def send(self, event: EventSpec) -> None:
        record = record_for(event, self.now())
        if event.kind == steps.VALID:
            self.kafka.send_valid(record)
            return
        headers = {"event_id": event.event_id, "correlation_id": event.correlation_id}
        key = event.member_number.encode()
        if event.kind == steps.UNKNOWN_SCHEMA_VERSION:
            self.kafka.send_raw(key, self.kafka.serialize(record), {**headers, "schema_version": UNKNOWN_VERSION})
        elif event.kind == steps.UNDECODABLE:
            self.kafka.send_raw(key, b"\x00not-avro " + event.event_id.encode(), {**headers, "schema_version": "1"})
        else:
            raise ValueError(f"unknown event kind {event.kind!r}")

    # ---- knobs ----
    def ledger_control(self, step: LedgerControl) -> None:
        status = self.post_control(control_body(step, self.now()))
        if status != 200:
            raise RuntimeError(f"the ledger's control endpoint answered {status}")

    def compose(self, step: Compose) -> None:
        command, extra = compose_command(step)
        code = self.run_command(command, extra)
        if code != 0:
            raise RuntimeError(f"`{' '.join(command[len(COMPOSE) :])}` exited {code}")

    def role_login(self, step: RoleLogin) -> None:
        role = Database(step.database).role_name(step.role)  # refuses anything but a known runtime role
        with self.connect("") as conn:
            # The role name is built from fixed lowercase names above, never from input.
            conn.execute(f'ALTER ROLE "{role}" {"LOGIN" if step.allowed else "NOLOGIN"}')
            if not step.allowed:
                conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = %s", (role,))

    # ---- the scenario's own evidence rows ----
    def record_change(self, step: RecordChange) -> None:
        with self.connect("ops") as conn:
            conn.execute(
                "INSERT INTO change_event (service, setting, old_value, new_value, source)"
                " VALUES (%s, %s, %s, %s, 'scenario')",
                (step.service, step.setting, step.old, step.new),
            )

    def record_question(self, step: RecordQuestion) -> None:
        with self.connect("ops") as conn:
            conn.execute(
                "INSERT INTO member_question (member_number, stay_id, question) VALUES (%s, %s, %s)",
                (step.member_number, step.stay_id, QUESTION),
            )

    def plant_log(self, step: PlantLog) -> None:
        with self.connect("ops") as conn:
            conn.execute(
                "INSERT INTO log_event (service, level, logger, message, correlation_id)"
                " VALUES ('posting', 'WARNING', 'app.pipeline.posting', %s, %s)",
                (step.message, step.correlation_id),
            )

    def plant_runbook(self, step: PlantRunbook) -> None:
        with self.connect("ops") as conn:
            conn.execute(
                "INSERT INTO runbook_section (runbook, title, body, tag) VALUES (%s, %s, %s, %s)",
                (PLANTED_RUNBOOK, "Note added during an incident", step.line, step.tag),
            )

    def remove_runbook(self, step: RemoveRunbook) -> None:
        if not step.tag:
            raise ValueError("refusing to remove runbook lines without a tag")
        with self.connect("ops") as conn:
            conn.execute("DELETE FROM runbook_section WHERE tag = %s", (step.tag,))  # only what a trigger planted

    def join_group(self, group: str) -> Callable[[], None]:
        return self.kafka.join_group(group)

    # ---- read-only conditions ----
    def count(self, condition: str) -> int:
        if condition == "lag":
            return self.kafka.lag()
        with self.connect("posting") as conn:
            return int(conn.execute(COUNT_SQL[condition]).fetchone()[0])

    def missing(self, condition: str, event_ids: tuple[str, ...]) -> tuple[str, ...]:
        wanted = list(event_ids)
        with self.connect("posting") as conn:
            if condition == "posted":
                rows = conn.execute("SELECT event_id FROM posting WHERE event_id = ANY(%s)", (wanted,)).fetchall()
                found = {row[0] for row in rows}
            elif condition == "dead_lettered":
                rows = conn.execute(
                    "SELECT event_id FROM parked_event WHERE status = 'dead' AND event_id = ANY(%s)", (wanted,)
                ).fetchall()
                found = {row[0] for row in rows}
                if len(found) < len(wanted):  # an event that was never parked is only in the dead-letter topic
                    found |= self.kafka.dead_letter_event_ids()
            else:
                raise ValueError(f"unknown event condition {condition!r}")
        return tuple(event_id for event_id in event_ids if event_id not in found)

    def signals(self) -> dict[str, float]:
        with self.connect("posting") as conn:
            row = conn.execute(SIGNALS_SQL).fetchone()
        names = (
            "posted_in_window",
            "posted_in_previous_window",
            "dead_lettered_in_window",
            "parked_open",
            "parked_oldest_age_seconds",
            "outbox_unpublished",
            "outbox_oldest_age_seconds",
        )
        snapshot = {name: float(value) for name, value in zip(names, row, strict=True)}
        snapshot["consumer_lag"] = float(self.kafka.lag())
        return snapshot

    def firing_alerts(self) -> list[str]:
        """Evaluate every rule on a fresh snapshot, store each evaluation, and return the rules that fired."""
        from psycopg.types.json import Jsonb

        evaluations = alerts.evaluate(self.rules, self.signals())
        with self.connect("ops") as conn:
            for evaluation in evaluations:
                conn.execute(
                    "INSERT INTO alert_evaluation (rule, state, signals, missing) VALUES (%s, %s, %s, %s)",
                    (
                        evaluation.rule,
                        evaluation.state,
                        Jsonb(dict(evaluation.values)),
                        Jsonb(list(evaluation.missing)),
                    ),
                )
        return alerts.firing(evaluations)


def run_compose(command: list[str], extra_env: dict[str, str], cwd: str) -> int:
    """Run a fixed `docker compose` command. Output goes to the terminal; Compose reads `.env` itself."""
    env = {**os.environ, **extra_env}
    return subprocess.run(command, cwd=cwd, env=env, check=False).returncode  # noqa: S603 (built by compose_command)
