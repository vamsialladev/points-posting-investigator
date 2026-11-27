"""The scenario's real side effects, checked offline with fakes: what is sent where, and what is refused.

The Kafka-facing lines (`app/scenarios/kafka_io.py`) and a full trigger and reset run on the real stack.
"""

from __future__ import annotations

import contextlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from app.ops import alerts
from app.pipeline import events as pipeline_events
from app.pipeline.ledger_client import ledger_timeout
from app.scenarios import catalog, plans, run, stack, steps
from app.scenarios.__main__ import main
from app.scenarios.executor import Executor

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
LOCAL = {
    "DATABASE_URL": "postgresql+psycopg://points:x@localhost:5432/points",
    "LEDGER_API_URL": "http://127.0.0.1:8020",
    "SCHEMA_REGISTRY_URL": "http://127.0.0.1:8081",
    "KAFKA_BOOTSTRAP_SERVERS": "127.0.0.1:9092",
}


class Db:
    """Records every statement per database, and answers reads from `answers` (matched by a fragment)."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, str, tuple]] = []
        self.answers: dict[str, list] = {}

    def connect(self, base: str):
        db = self

        class Conn:
            def execute(self, query, params=None):
                db.statements.append((base, " ".join(query.split()), tuple(params or ())))
                rows = next((rows for fragment, rows in db.answers.items() if fragment in query), [])

                class Result:
                    def fetchone(self):
                        return rows[0] if rows else None

                    def fetchall(self):
                        return rows

                return Result()

        @contextmanager
        def manager():
            yield Conn()

        return manager()


@pytest.fixture
def world():
    sent: list[tuple] = []
    db = Db()
    control: list[dict] = []
    commands: list[tuple] = []
    state = {"lag": 0, "dlq": set(), "control_status": 200, "command_code": 0}
    kafka = stack.Kafka(
        send_valid=lambda record: sent.append(("valid", record)),
        send_raw=lambda key, value, headers: sent.append(("raw", key, value, headers)),
        serialize=lambda record: b"AVRO:" + record["event_id"].encode(),
        lag=lambda: state["lag"],
        dead_letter_event_ids=lambda: set(state["dlq"]),
        join_group=lambda group: lambda: None,
    )
    effects = stack.StackEffects(
        kafka=kafka,
        connect=db.connect,
        post_control=lambda body: control.append(body) or state["control_status"],
        run_command=lambda command, extra: commands.append((command, extra)) or state["command_code"],
        rules=alerts.load(),
        now=lambda: NOW,
    )
    return effects, sent, db, control, commands, state


def test_a_valid_event_is_a_record_the_pipeline_accepts_stamped_now(world):
    effects, sent, *_ = world
    spec = plans.plan("S02").manifest.events[0]
    effects.send(spec)
    (kind, record) = sent[0]
    assert kind == "valid" and record["occurred_at"] == NOW and record["check_out"] == NOW.date()
    event = pipeline_events.validate(record, {"schema_version": "1", "event_id": spec.event_id})
    assert (event.member_number, event.stay_id, event.revision) == (spec.member_number, spec.stay_id, spec.revision)


def test_a_skewed_event_is_stamped_hours_ahead(world):
    effects, sent, *_ = world
    effects.send(plans.plan("S13").manifest.events[0])
    assert sent[0][1]["occurred_at"] == NOW + timedelta(seconds=plans.SKEW_SECONDS)


def test_bad_events_are_sent_raw_with_the_members_key_and_the_event_id_header(world):
    effects, sent, *_ = world
    by_kind = {e.kind: e for e in plans.plan("S01").manifest.events}
    unknown, garbage = by_kind[steps.UNKNOWN_SCHEMA_VERSION], by_kind[steps.UNDECODABLE]
    effects.send(unknown)
    effects.send(garbage)
    (_, key, value, headers), (_, key2, value2, headers2) = sent
    assert key == unknown.member_number.encode() and value == b"AVRO:" + unknown.event_id.encode()
    assert headers["schema_version"] == stack.UNKNOWN_VERSION not in pipeline_events.SUPPORTED_SCHEMA_VERSIONS
    assert key2 == garbage.member_number.encode() and not value2.startswith(b"AVRO:")
    assert headers2 == {"event_id": garbage.event_id, "correlation_id": garbage.correlation_id, "schema_version": "1"}


def test_ledger_control_sends_only_the_knobs_the_step_names(world):
    effects, _, _, control, _, state = world
    effects.ledger_control(steps.LedgerControl(latency_ms=8000))
    effects.ledger_control(steps.LedgerControl(rate_per_sec=0.2, burst=1))
    effects.ledger_control(steps.LedgerControl(expire_token=True))
    effects.ledger_control(steps.LedgerControl(clear_token_expiry=True))
    assert control == [
        {"latency_ms": 8000},
        {"rate_per_sec": 0.2, "burst": 1},
        {"token_expires_at": (NOW - timedelta(hours=1)).isoformat()},
        {"clear_token_expiry": True},
    ]
    state["control_status"] = 401
    with pytest.raises(RuntimeError, match="answered 401"):
        effects.ledger_control(steps.LedgerControl(latency_ms=0))
    for bad in (steps.LedgerControl(), steps.LedgerControl(expire_token=True, clear_token_expiry=True)):
        with pytest.raises(ValueError):
            stack.control_body(bad, NOW)


def test_compose_runs_fixed_commands_for_known_services_only(world):
    effects, _, _, _, commands, state = world
    effects.compose(steps.Compose("stop", ("relay",)))
    effects.compose(steps.Compose("up", ("posting", "retry-worker"), env=(("LEDGER_TIMEOUT_SECONDS", "0.001"),)))
    assert commands[0] == (["docker", "compose", "--profile", "core", "stop", "relay"], {})
    assert commands[1][0][4:] == ["up", "-d", "--no-deps", "--wait", "--wait-timeout", "120", "posting", "retry-worker"]
    assert commands[1][1] == {"LEDGER_TIMEOUT_SECONDS": "0.001"}
    state["command_code"] = 1
    with pytest.raises(RuntimeError, match="exited 1"):
        effects.compose(steps.Compose("start", ("relay",)))


@pytest.mark.parametrize(
    "step",
    [
        steps.Compose("down", ("relay",)),  # not an allowed action
        steps.Compose("stop", ("db",)),  # not a service a scenario may touch
        steps.Compose("stop", ("kafka",)),
        steps.Compose("stop", ()),
        steps.Compose("up", ("posting",), env=(("LEDGER_API_TOKEN", "x"),)),  # not an overridable setting
        steps.Compose("restart", ("posting",), env=(("LEDGER_TIMEOUT_SECONDS", "1"),)),  # settings need `up`
        steps.Compose("stop", ("relay", "-v")),
    ],
)
def test_compose_refuses_everything_else(step):
    with pytest.raises(ValueError):
        stack.compose_command(step)


def test_role_login_switches_one_known_role_and_ends_its_sessions(world):
    effects, _, db, *_ = world
    effects.role_login(steps.RoleLogin("posting", "app", allowed=False))
    effects.role_login(steps.RoleLogin("posting", "app", allowed=True))
    assert [s[1] for s in db.statements] == [
        'ALTER ROLE "posting_app" NOLOGIN',
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = %s",
        'ALTER ROLE "posting_app" LOGIN',
    ]
    assert db.statements[1][2] == ("posting_app",)
    for database, role in (("posting", "owner"), ("points", "app"), ("posting", 'app"; DROP ROLE x; --')):
        with pytest.raises(ValueError):
            effects.role_login(steps.RoleLogin(database, role, allowed=False))


def test_evidence_rows_go_to_the_ops_database_with_values_as_parameters(world):
    effects, _, db, *_ = world
    effects.record_change(steps.RecordChange("posting", "LEDGER_TIMEOUT_SECONDS", "5.0", "0.001"))
    effects.record_question(steps.RecordQuestion("GR-30000", "BR-0100"))
    effects.plant_log(steps.PlantLog(catalog.INJECTION_LOG_MESSAGE, catalog.INJECTION_CORRELATION_ID))
    effects.plant_runbook(steps.PlantRunbook(catalog.INJECTION_RUNBOOK_LINE, "S17-run0"))
    effects.remove_runbook(steps.RemoveRunbook("S17-run0"))
    assert {s[0] for s in db.statements} == {"ops"}
    assert db.statements[0][2] == ("posting", "LEDGER_TIMEOUT_SECONDS", "5.0", "0.001")
    assert db.statements[1][2] == ("GR-30000", "BR-0100", stack.QUESTION)
    assert db.statements[2][2] == (catalog.INJECTION_LOG_MESSAGE, catalog.INJECTION_CORRELATION_ID)
    assert db.statements[4][1] == "DELETE FROM runbook_section WHERE tag = %s" and db.statements[4][2] == ("S17-run0",)
    for query, _params in ((s[1], s[2]) for s in db.statements):
        assert "ignore previous" not in query and "SYSTEM:" not in query, "planted text is never part of the SQL"
    with pytest.raises(ValueError):
        effects.remove_runbook(steps.RemoveRunbook(""))


def test_nothing_ever_writes_to_the_pipelines_own_tables(world):
    effects, _, db, *_ = world
    for scenario, pair in [(s, None) for s in catalog.SCENARIOS if s != "S15"] + [("S15", "A"), ("S15", "B")]:
        built = plans.plan(scenario, 0, pair)
        for phase in (built.trigger, built.reset):
            with contextlib.suppress(Exception):  # the fakes don't satisfy every wait; only the statements matter
                instant(effects).run(phase)
    written = [s for s in db.statements if s[1].split()[0] in ("INSERT", "UPDATE", "DELETE", "ALTER", "TRUNCATE")]
    assert written, "the scenarios did write their own evidence rows"
    for base, query, _ in written:
        assert base in ("ops", ""), f"a scenario wrote to {base}: {query}"
        assert not any(t in query for t in (" posting", " outbox", " parked_event", " skipped_event", " credits"))


def test_counts_and_event_conditions_read_the_right_places(world):
    effects, _, db, _, _, state = world
    state["lag"] = 17
    db.answers = {"FROM parked_event WHERE status IN": [(4,)], "FROM outbox WHERE status IN": [(9,)]}
    assert (effects.count("lag"), effects.count("parked_open"), effects.count("outbox_unpublished")) == (17, 4, 9)
    db.answers = {"FROM posting WHERE event_id": [("e1",)], "status = 'dead'": [("e2",)]}
    assert effects.missing("posted", ("e1", "e2")) == ("e2",)
    state["dlq"] = {"e3"}
    assert effects.missing("dead_lettered", ("e2", "e3", "e4")) == ("e4",)  # parked-dead, or only in the topic
    with pytest.raises(ValueError):
        effects.missing("credited", ("e1",))


def test_alerts_are_evaluated_on_a_fresh_snapshot_and_every_evaluation_is_stored(world):
    effects, _, db, _, _, state = world
    state["lag"] = 0
    db.answers = {"FROM posting WHERE posted_at": [(0, 20, 0, 0, 0, 0, 0)]}  # a burst a while ago, quiet now
    assert effects.firing_alerts() == [plans.ALERT_POSTINGS_DROPPED]
    stored = [s for s in db.statements if s[1].startswith("INSERT INTO alert_evaluation")]
    assert len(stored) == len(alerts.load()) and {s[0] for s in stored} == {"ops"}
    states = {s[2][0]: s[2][1] for s in stored}
    assert states[plans.ALERT_POSTINGS_DROPPED] == "firing" and states["consumer_lag_high"] == "quiet"
    assert set(effects.signals()) == alerts.SIGNALS, "the snapshot gives every signal the rules may use"


@pytest.mark.parametrize(
    "change",
    [
        {"PUBLIC_DEMO_MODE": "true"},
        {"DATABASE_URL": "postgresql+psycopg://points:x@db.example.com:5432/points"},
        {"LEDGER_API_URL": "https://ledger.example.com"},
        {"SCHEMA_REGISTRY_URL": "http://10.0.0.5:8081"},
        {"KAFKA_BOOTSTRAP_SERVERS": "127.0.0.1:9092,broker.example.com:9092"},
        {"KAFKA_BOOTSTRAP_SERVERS": ""},
    ],
)
def test_the_guard_refuses_anything_that_is_not_this_machine(change):
    stack.guard(LOCAL)  # the local settings pass
    with pytest.raises(stack.NotLocal) as refused:
        stack.guard({**LOCAL, **change})
    assert "x@" not in str(refused.value), "the refusal names the setting, never its value"


def test_ledger_timeout_setting_has_a_default_and_hard_edges():
    assert ledger_timeout({}) == 5.0 and ledger_timeout({"LEDGER_TIMEOUT_SECONDS": ""}) == 5.0
    assert ledger_timeout({"LEDGER_TIMEOUT_SECONDS": plans.LEDGER_TIMEOUT_BROKEN}) == 0.001
    assert ledger_timeout({"LEDGER_TIMEOUT_SECONDS": plans.LEDGER_TIMEOUT_DEFAULT}) == 5.0
    for bad in ("0", "-1", "121", "fast"):
        with pytest.raises(ValueError):
            ledger_timeout({"LEDGER_TIMEOUT_SECONDS": bad})


# ---- run.execute: the manifest ----


class Quiet:
    """Effects where every wait is met at once and nothing fails, unless `fail` names a method."""

    def __init__(self, fail: str = "") -> None:
        self.fail, self.sent = fail, 0

    def __getattr__(self, name):
        def effect(*args):
            if name == self.fail:
                raise ConnectionError("the stack is down")
            if name == "send":
                self.sent += 1
            return {"count": 10**6, "missing": (), "firing_alerts": [plans.ALERT_POSTINGS_DROPPED]}.get(name)

        return effect


def instant(effects) -> Executor:
    clock = {"t": 0.0}
    return Executor(effects, lambda: clock["t"], lambda s: clock.__setitem__("t", clock["t"] + s))


def test_a_trigger_writes_the_manifest_with_the_ground_truth_and_each_step(tmp_path):
    effects, said = Quiet(), []
    ok = run.execute("trigger", "S11", 2, None, effects, directory=tmp_path, now=lambda: NOW, say=said.append,
                     executor=instant(effects))  # fmt: skip
    assert ok and said[-1].startswith("ok; manifest:") and said[-1].endswith("S11-run2.json")
    document = json.loads((tmp_path / "S11-run2.json").read_text(encoding="utf-8"))
    assert document["manifest"]["root_causes"] == ["correction_before_original"]
    assert document["manifest"]["recovery"] == "dlq_replay" and len(document["manifest"]["replay_event_ids"]) == 1
    (phase,) = document["phases"]
    assert (phase["phase"], phase["ok"], phase["error"]) == ("trigger", True, None)
    assert [s["step"] for s in phase["steps"]] == [type(s).__name__ for s in plans.plan("S11", 2).trigger]
    assert phase["started_at"] == NOW.isoformat()


def test_a_reset_appends_to_the_same_manifest(tmp_path):
    effects = Quiet()
    for phase in ("trigger", "reset"):
        effects_for_phase = effects
        assert run.execute(phase, "S10", 0, None, effects_for_phase, directory=tmp_path, say=lambda _: None,
                           executor=instant(effects) if phase == "trigger" else _zero_counts(effects))  # fmt: skip
    document = json.loads((tmp_path / "S10-run0.json").read_text(encoding="utf-8"))
    assert [p["phase"] for p in document["phases"]] == ["trigger", "reset"]


def _zero_counts(effects) -> Executor:
    effects.count = lambda condition: 0  # the reset waits for "equals 0"
    return instant(effects)


def test_a_failed_step_is_recorded_and_reported_never_hidden(tmp_path):
    effects, said = Quiet(fail="ledger_control"), []
    ok = run.execute("trigger", "S03", 0, None, effects, directory=tmp_path, say=said.append, executor=instant(effects))
    assert not ok and effects.sent == 0, "the steps after the failure never ran"
    (phase,) = json.loads((tmp_path / "S03-run0.json").read_text(encoding="utf-8"))["phases"]
    assert phase["ok"] is False and "step 1 (LedgerControl) failed: ConnectionError" in phase["error"]
    assert any("run the reset" in line for line in said) and said[-1].startswith("NOT ok")


def test_a_manifest_from_a_different_plan_is_not_overwritten(tmp_path):
    path = run.manifest_path("S05", 0, None, tmp_path)
    path.write_text(
        json.dumps({"manifest": {"scenario": "S05", "run": 0, "events": []}, "phases": []}), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="different plan"):
        run.execute("trigger", "S05", 0, None, Quiet(), directory=tmp_path, say=lambda _: None)
    assert run.manifest_path("S15", 3, "B", tmp_path).name == "S15-B-run3.json"
    with pytest.raises(ValueError):
        run.execute("replay", "S05", 0, None, Quiet(), directory=tmp_path)


def test_the_command_refuses_to_trigger_when_the_stack_settings_are_not_local(capsys):
    def not_local():
        stack.guard({**LOCAL, "PUBLIC_DEMO_MODE": "true"})

    assert main(["trigger", "S05"], effects=not_local) == 2
    assert "refused: NotLocal" in capsys.readouterr().err
