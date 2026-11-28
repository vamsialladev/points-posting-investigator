"""Fixtures shared by every real-infrastructure test (markers `postgres` and `kafka`). Loaded by tests/conftest.py.

- Postgres: TEST_DATABASE_URL is the stack's superuser URL. The session bootstraps separate `test_` roles and
  databases with fresh random passwords (never printed), so the running stack's data is never touched.
- Kafka: TEST_KAFKA_BOOTSTRAP_SERVERS and TEST_SCHEMA_REGISTRY_URL.
scripts\\test_integration.ps1 sets all three without printing them. Without them these fixtures skip, and under
REQUIRE_MARKERS (CI) a skip is a failure.
"""

from __future__ import annotations

import os
import secrets

import psycopg
import pytest
from confluent_kafka.schema_registry import SchemaRegistryClient
from sqlalchemy.engine import URL, make_url

from app.db.bootstrap import bootstrap, conninfo
from app.db.roles import PASSWORD_VARIABLES, Database, runtime_url
from app.pipeline import kafka_auth

PREFIX = "test_"
LEDGER = Database("ledger", PREFIX)
POSTING = Database("posting", PREFIX)
HOW = "run scripts\\stack.ps1 up, then scripts\\test_integration.ps1"


@pytest.fixture(scope="session")
def admin() -> URL:
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        pytest.skip(f"TEST_DATABASE_URL is not set: {HOW}")
    return make_url(raw)


@pytest.fixture(scope="session")
def passwords(admin: URL) -> dict[str, str]:
    generated = {variable: secrets.token_urlsafe(18) for variable in PASSWORD_VARIABLES}  # per session, never printed
    bootstrap(admin, generated, prefix=PREFIX, reset=True)
    return generated


@pytest.fixture(scope="session")
def host(admin: URL) -> dict[str, object]:
    return {"host": admin.host or "localhost", "port": admin.port or 5432}


@pytest.fixture(scope="session")
def kafka() -> str:
    servers = os.environ.get("TEST_KAFKA_BOOTSTRAP_SERVERS")
    if not servers:
        pytest.skip(f"TEST_KAFKA_BOOTSTRAP_SERVERS is not set: {HOW}")
    return servers.replace("localhost", "127.0.0.1")


@pytest.fixture(scope="session")
def registry() -> SchemaRegistryClient:
    url = os.environ.get("TEST_SCHEMA_REGISTRY_URL")
    if not url:
        pytest.skip(f"TEST_SCHEMA_REGISTRY_URL is not set: {HOW}")
    # Bounded: the client has no timeout by default, and Karapace answers TimeoutError for a while after a Kafka
    # restart, so an unbounded cleanup call stretched one outage-test run far past its ~100 s (verification log).
    return SchemaRegistryClient({"url": url.replace("://localhost", "://127.0.0.1"), "timeout": 10, "max.retries": 2})


def admin_kafka(bootstrap: str) -> dict[str, object]:
    """Connection settings for a test's own Kafka client: the broker's admin, which may use any scratch topic and
    group (ADR-0021). Plain settings when the stack has no SASL."""
    return kafka_auth.client_config(kafka_auth.ADMIN, bootstrap)


def role_url(database: Database, passwords: dict[str, str], host: dict[str, object], role: str = "app") -> URL:
    variable = next(r.password_variable for r in database.roles if r.suffix == role)
    return runtime_url(database, passwords[variable], role=role, **host)  # type: ignore[arg-type]


def runtime_connect(
    database: Database, passwords: dict[str, str], host: dict[str, object], role: str = "app"
) -> psycopg.Connection:
    return psycopg.connect(**conninfo(role_url(database, passwords, host, role)), autocommit=True)


def admin_connect(admin: URL, database: Database) -> psycopg.Connection:
    return psycopg.connect(**conninfo(admin, database.name), autocommit=True)
