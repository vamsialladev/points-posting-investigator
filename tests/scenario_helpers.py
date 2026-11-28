"""Shared by the real-stack scenario tests (tests/test_scenarios_real.py, tests/test_scenarios_batch.py).

The `effects` fixture is loaded by tests/conftest.py. It needs TEST_DATABASE_URL, TEST_KAFKA_BOOTSTRAP_SERVERS,
TEST_SCHEMA_REGISTRY_URL, TEST_LEDGER_URL and TEST_LEDGER_TOKEN (scripts\\test_integration.ps1 sets them without
printing them); without them it skips, and under REQUIRE_MARKERS a skip is a failure.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

import pytest

from app.scenarios import catalog, plans, run

RUNS_FOR_TESTS = range(plans.MAX_RUN, 5, -1)  # the top of the range; demo runs count up from 0
MAPPING = {
    "DATABASE_URL": "TEST_DATABASE_URL",
    "KAFKA_BOOTSTRAP_SERVERS": "TEST_KAFKA_BOOTSTRAP_SERVERS",
    "SCHEMA_REGISTRY_URL": "TEST_SCHEMA_REGISTRY_URL",
    "LEDGER_API_URL": "TEST_LEDGER_URL",
    "LEDGER_API_TOKEN": "TEST_LEDGER_TOKEN",
}


@pytest.fixture(scope="session")
def effects():
    env = {name: os.environ.get(source, "") for name, source in MAPPING.items()}
    missing = [MAPPING[name] for name, value in env.items() if not value]
    if missing:
        pytest.skip(f"{', '.join(missing)} not set: run scripts\\stack.ps1 up, then scripts\\test_integration.ps1")
    return run.stack_effects(env)


@pytest.fixture(scope="session")
def evidence_readers(effects):
    """(EvidenceStore, TopicReader) on the stack, logged in as the read-only roles and the `investigator` Kafka
    login. A missing login is a skip, which is a failure under REQUIRE_MARKERS."""
    from sqlalchemy.engine import make_url

    from app.evidence.snapshot import reader_from_env
    from app.evidence.store import EvidenceStore, engines_from_env

    needed = ("INVESTIGATOR_DB_PASSWORD", "KAFKA_INVESTIGATOR_PASSWORD")
    missing = [name for name in needed if not os.environ.get(name)]
    if missing:
        pytest.skip(f"{', '.join(missing)} not set: the stack's read-only logins are needed to read evidence")
    admin = make_url(os.environ["TEST_DATABASE_URL"])
    env = {
        "INVESTIGATOR_DB_PASSWORD": os.environ["INVESTIGATOR_DB_PASSWORD"],
        "KAFKA_INVESTIGATOR_PASSWORD": os.environ["KAFKA_INVESTIGATOR_PASSWORD"],
        "POSTGRES_HOST": admin.host or "127.0.0.1",
        "POSTGRES_PORT": str(admin.port or 5432),
        "KAFKA_BOOTSTRAP_SERVERS": os.environ["TEST_KAFKA_BOOTSTRAP_SERVERS"],
        "SCHEMA_REGISTRY_URL": os.environ["TEST_SCHEMA_REGISTRY_URL"],
    }
    return EvidenceStore(engines_from_env(env)), reader_from_env(env)


def capture(evidence_readers, name: str, since: datetime):
    """Take a read-only snapshot of the evidence since `since` and keep it under `.scenario-runs/evidence/`, where
    the workflow uploads it. Returns the snapshot."""
    from app.evidence.snapshot import collect

    store, reader = evidence_readers
    snapshot = collect(store, reader, since)
    folder = run.RUNS_DIR / "evidence"
    folder.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"scenario_run": name, **snapshot.to_json()}, indent=2, default=str)
    (folder / f"{name}.json").write_text(text + "\n", encoding="utf-8", newline="\n")
    return snapshot


def started() -> datetime:
    """A moment just before a trigger: the start of the window its evidence is read from."""
    return datetime.now(UTC) - timedelta(seconds=5)


def rows(effects, base: str, query: str, params: tuple = ()) -> list[tuple]:
    with effects.connect(base) as conn:
        return conn.execute(query, params).fetchall()


def free_run(effects, scenario: str) -> int:
    """The first run of this scenario that left nothing on this stack yet, so the trigger behaves as on a new one.
    S15's two pairs share one block per run, so a run is free only if neither pair used it."""
    pairs = tuple(catalog.S15_PAIRS) if scenario == "S15" else (None,)
    for number in RUNS_FOR_TESTS:
        manifests = [plans.plan(scenario, number, pair).manifest for pair in pairs]
        ids = [event.event_id for each in manifests for event in each.events]
        if ids:
            used = rows(effects, "posting", "SELECT 1 FROM posting WHERE event_id = ANY(%s) LIMIT 1", (ids,))
            used += rows(effects, "posting", "SELECT 1 FROM parked_event WHERE event_id = ANY(%s) LIMIT 1", (ids,))
            used += [1] if set(ids) & effects.kafka.dead_letter_event_ids() else []
        else:
            member = manifests[0].affected[0].member_number
            used = rows(effects, "ops", "SELECT 1 FROM member_question WHERE member_number = %s LIMIT 1", (member,))
        if not used:
            return number
    pytest.fail(f"every test run of {scenario} is used on this stack: scripts\\stack.ps1 reset clears it (ask first)")


def credits_for(effects, events) -> dict[str, int]:
    keys = [f"{event.stay_id}:{event.revision}" for event in events]
    found = rows(effects, "ledger", "SELECT idempotency_key FROM credits WHERE idempotency_key = ANY(%s)", (keys,))
    counts: dict[str, int] = {}
    for (key,) in found:
        counts[key] = counts.get(key, 0) + 1
    return counts
