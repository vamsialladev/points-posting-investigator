"""The ledger and the database roles against real Postgres (RFC-0001 D9, D11; standing rule 7).

Needs TEST_DATABASE_URL (the stack's superuser URL; scripts\\test_integration.ps1 sets it without printing it).
Everything runs in separate `test_` roles and databases, recreated per session, so the running stack is untouched.
Without the URL these tests skip, and under REQUIRE_MARKERS=postgres (CI) a skip is a failure.
"""

from __future__ import annotations

import os
import secrets
import threading
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import errors
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url

from app.db import migrate
from app.db.bootstrap import bootstrap, conninfo
from app.db.roles import GRANTS, Database, runtime_url
from app.ledger.api import create_app
from app.ledger.core import CreditRequest, LedgerSettings
from app.ledger.schema import credits
from app.ledger.store import IdempotencyConflict, PostgresCreditStore
from tests.ledger_checks import credit_problems

pytestmark = pytest.mark.postgres
PREFIX = "test_"
LEDGER = Database("ledger", PREFIX)
POSTING = Database("posting", PREFIX)
REQUEST = CreditRequest("GR-00001", "BR-0001", 4500, "corr-1")


@pytest.fixture(scope="session")
def admin() -> URL:
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("TEST_DATABASE_URL is not set: run scripts\\stack.ps1 up, then scripts\\test_integration.ps1")
    return make_url(raw)


@pytest.fixture(scope="session")
def passwords(admin: URL) -> dict[str, str]:
    generated = {base: secrets.token_urlsafe(18) for base in GRANTS}  # fresh per session, never printed
    bootstrap(admin, generated, prefix=PREFIX, reset=True)
    return generated


@pytest.fixture(scope="session")
def host(admin: URL) -> dict[str, object]:
    return {"host": admin.host or "localhost", "port": admin.port or 5432}


@pytest.fixture
def ledger_engine(passwords: dict[str, str], host: dict[str, object], admin: URL) -> Iterator[Engine]:
    with psycopg.connect(**conninfo(admin, LEDGER.name), autocommit=True) as conn:
        conn.execute("TRUNCATE credits")  # as the superuser: the runtime role can't, which is tested below
        conn.execute("ALTER SEQUENCE credit_entry_seq RESTART")
    engine = create_engine(runtime_url(LEDGER, passwords["ledger"], **host))  # type: ignore[arg-type]
    yield engine
    engine.dispose()


def runtime_connect(database: Database, password: str, host: dict[str, object]) -> psycopg.Connection:
    url = runtime_url(database, password, **host)  # type: ignore[arg-type]
    return psycopg.connect(**conninfo(url), autocommit=True)


def test_a_credit_then_a_replay_then_a_conflict(ledger_engine):
    store = PostgresCreditStore(ledger_engine)
    first, created = store.credit("evt-1", REQUEST)
    assert created and first.entry_id == "L-0000001"
    again, created_again = store.credit("evt-1", REQUEST)
    assert not created_again and again.entry_id == first.entry_id
    with pytest.raises(IdempotencyConflict) as conflict:
        store.credit("evt-1", CreditRequest("GR-00001", "BR-0001", 9999, "corr-2"))
    assert conflict.value.existing.entry_id == "L-0000001"
    with ledger_engine.connect() as conn:
        assert credit_problems(conn, {"evt-1": 4500}) == []


def test_concurrent_credits_for_one_key_store_exactly_one(ledger_engine):
    store = PostgresCreditStore(ledger_engine)
    results, failures = [], []
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        try:
            results.append(store.credit("evt-race", REQUEST))
        except Exception as exc:  # recorded and asserted on below
            failures.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert failures == []
    assert sorted(created for _, created in results) == [False] * 7 + [True]
    assert {credit.entry_id for credit, _ in results} == {"L-0000001"}
    with ledger_engine.connect() as conn:
        assert credit_problems(conn, {"evt-race": 4500}) == []


def test_the_duplicate_check_can_fail(ledger_engine, admin):
    """Rule 7: prove credit_problems isn't a check that passes on anything."""
    PostgresCreditStore(ledger_engine).credit("evt-1", REQUEST)
    with ledger_engine.connect() as conn:
        assert credit_problems(conn, {}) == ["evt-1: unexpected credit"]
        assert credit_problems(conn, {"evt-1": 4500, "evt-2": 10}) == ["evt-2: no credit"]
        assert credit_problems(conn, {"evt-1": 1}) == ["evt-1: 4500 points, expected 1"]


def test_postgres_refuses_a_second_row_for_one_key_even_for_the_superuser(ledger_engine, admin):
    PostgresCreditStore(ledger_engine).credit("evt-1", REQUEST)
    with (
        psycopg.connect(**conninfo(admin, LEDGER.name), autocommit=True) as conn,
        pytest.raises(errors.UniqueViolation),
    ):
        conn.execute(
            "INSERT INTO credits (idempotency_key, request_hash, member_number, stay_id, points, correlation_id)"
            " VALUES ('evt-1', 'h', 'GR-00001', 'BR-0001', 1, 'c')"
        )


@pytest.mark.parametrize(
    "statement",
    ["UPDATE credits SET points = 1", "DELETE FROM credits", "TRUNCATE credits", "DROP TABLE credits"],
)
def test_the_ledger_runtime_role_cannot_change_or_remove_a_credit(ledger_engine, passwords, host, statement):
    PostgresCreditStore(ledger_engine).credit("evt-1", REQUEST)
    with runtime_connect(LEDGER, passwords["ledger"], host) as conn, pytest.raises(errors.InsufficientPrivilege):
        conn.execute(statement)
    with ledger_engine.connect() as conn:
        assert credit_problems(conn, {"evt-1": 4500}) == []


def test_bad_shapes_are_refused_by_the_database_too(ledger_engine):
    with ledger_engine.begin() as conn, pytest.raises(Exception, match="credits_member_number_format"):
        conn.execute(
            credits.insert().values(
                idempotency_key="k",
                request_hash="h",
                member_number="X",
                stay_id="BR-0001",
                points=1,
                correlation_id="c",
            )
        )


def test_owner_roles_cannot_log_in_and_runtime_roles_are_not_privileged(admin):
    with psycopg.connect(**conninfo(admin), autocommit=True) as conn:
        rows = conn.execute(
            "SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = ANY(%s)",
            ([d.owner for d in (LEDGER, POSTING)] + [d.runtime for d in (LEDGER, POSTING)],),
        ).fetchall()
    roles = {name: rest for name, *rest in rows}
    assert roles["test_ledger_owner"][0] is False and roles["test_posting_owner"][0] is False
    for runtime in ("test_ledger_app", "test_posting_app"):
        assert roles[runtime] == [True, False, False, False]


def test_a_runtime_role_cannot_reach_the_other_database(passwords, host):
    url = runtime_url(Database("posting", PREFIX), passwords["ledger"], **host)  # type: ignore[arg-type]
    wrong = url.set(username=LEDGER.runtime)
    with pytest.raises(psycopg.OperationalError, match=r"permission denied|not have CONNECT"):
        psycopg.connect(**conninfo(wrong)).close()


@pytest.mark.parametrize(
    ("table", "privilege", "expected"),
    [
        ("posting", "SELECT", True),
        ("posting", "INSERT", True),
        ("posting", "UPDATE", False),
        ("posting", "DELETE", False),
        ("outbox", "INSERT", True),
        ("outbox", "DELETE", False),
    ],
)
def test_posting_runtime_rights(passwords, admin, table, privilege, expected):
    with psycopg.connect(**conninfo(admin, POSTING.name), autocommit=True) as conn:
        row = conn.execute("SELECT has_table_privilege(%s, %s, %s)", (POSTING.runtime, table, privilege)).fetchone()
    assert row is not None and row[0] is expected


@pytest.mark.parametrize(
    ("column", "expected"),
    [("published_at", True), ("attempts", True), ("last_error", True), ("payload", False), ("topic", False)],
)
def test_the_relay_may_mark_outbox_rows_but_not_rewrite_them(passwords, admin, column, expected):
    with psycopg.connect(**conninfo(admin, POSTING.name), autocommit=True) as conn:
        row = conn.execute(
            "SELECT has_column_privilege(%s, 'outbox', %s, 'UPDATE')", (POSTING.runtime, column)
        ).fetchone()
    assert row is not None and row[0] is expected


def test_bootstrap_runs_again_without_changing_anything(admin, passwords, ledger_engine):
    PostgresCreditStore(ledger_engine).credit("evt-1", REQUEST)
    bootstrap(admin, passwords, prefix=PREFIX)  # no reset: data must survive
    with ledger_engine.connect() as conn:
        assert credit_problems(conn, {"evt-1": 4500}) == []


def test_a_rotated_database_password_locks_out_the_old_one(admin, passwords, host):
    rotated = {**passwords, "ledger": secrets.token_urlsafe(18)}
    bootstrap(admin, rotated, prefix=PREFIX)
    try:
        with pytest.raises(psycopg.OperationalError, match="password authentication failed"):
            runtime_connect(LEDGER, passwords["ledger"], host).close()
        runtime_connect(LEDGER, rotated["ledger"], host).close()
    finally:
        bootstrap(admin, passwords, prefix=PREFIX)  # put the session's password back


def test_migrations_round_trip_and_match_the_code(admin, passwords):
    for database in (LEDGER, POSTING):
        migrate.downgrade(admin, database)
        migrate.upgrade(admin, database)
        migrate.check(admin, database)  # raises if the migrated schema drifts from the SQLAlchemy tables
    bootstrap(admin, passwords, prefix=PREFIX)  # tables were recreated: grant again


def test_the_api_over_real_postgres(ledger_engine):
    client = TestClient(create_app(PostgresCreditStore(ledger_engine), LedgerSettings(token="fake-ledger-token-1")))
    headers = {"Authorization": "Bearer fake-ledger-token-1", "Idempotency-Key": "evt-api"}
    body = {"member_number": "GR-00002", "stay_id": "ML-0002", "points": 1200, "correlation_id": "corr-api"}
    assert client.post("/v1/credits", json=body, headers=headers).status_code == 201
    assert client.post("/v1/credits", json=body, headers=headers).status_code == 200
    assert client.post("/v1/credits", json={**body, "points": 1}, headers=headers).status_code == 409
    assert client.get("/v1/credits/evt-api", headers=headers).json()["points"] == 1200
    assert client.get("/readyz").status_code == 200
    with ledger_engine.connect() as conn:
        assert credit_problems(conn, {"evt-api": 1200}) == []
        assert conn.execute(text("SELECT current_user")).scalar() == "test_ledger_app"
