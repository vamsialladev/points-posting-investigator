"""Who may connect to which database, and with which rights (RFC-0001 D9, Stage 9's owner/runtime lesson).

Each database has:
- an **owner** that owns the tables and runs migrations. It has NOLOGIN: the bootstrap connects as the Postgres
  superuser and runs migrations under `SET ROLE <owner>`, so no service ever holds an owner password.
- one or more **runtime** roles, each with only the rights its service needs:
  - `ledger_app`: the ledger mock. It can't UPDATE or DELETE a credit, so a second credit or an edited one is
    refused by Postgres even if application code is wrong.
  - `posting_app`: the posting service. It inserts postings and outbox rows, and never changes an outbox row.
  - `posting_relay`: the outbox relay (approved 2026-11-22, ADR-0014). It reads the outbox and may change only the
    delivery columns. It can't add, delete or rewrite a message, and can't read the posting table.

A prefix (`test_`, `ci_`) gives tests and local CI their own roles and databases, so they never touch the stack's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.engine import URL

_PREFIX = re.compile(r"[a-z_]{0,16}")


@dataclass(frozen=True)
class RuntimeRole:
    suffix: str  # the role is <prefix><database>_<suffix>
    password_variable: str  # where the password comes from (.env, CI's masked value); never printed
    grants: dict[str, str]  # "KIND name" -> privileges; anything not listed is refused
    read_only: bool = False  # every transaction of this role starts read-only (a second guard behind the grants)


INVESTIGATOR = "investigator"
# RFC-0002: the investigator and the rules baseline read stored evidence through these roles. SELECT only, on
# every database; never the raw bytes of a parked event (`raw_key`, `raw_value`), which they have no use for.
_PARKED_READABLE = (
    "id, event_id, member_number, stay_id, revision, raw_headers, source_topic, source_partition, source_offset,"
    " status, attempts, transient_failures, next_attempt_at, claimed_by, lease_until, error_class, last_error,"
    " first_failed_at, last_failed_at, parked_at, done_at, dead_at"
)


def _reader(grants: dict[str, str]) -> RuntimeRole:
    return RuntimeRole(INVESTIGATOR, "INVESTIGATOR_DB_PASSWORD", grants, read_only=True)


# tests/test_ledger_postgres.py and tests/test_relay_postgres.py check each grant against the real database, both
# what is allowed and what is not.
RUNTIME_ROLES: dict[str, tuple[RuntimeRole, ...]] = {
    "ledger": (
        RuntimeRole(
            "app",
            "LEDGER_DB_PASSWORD",
            {"TABLE credits": "SELECT, INSERT", "SEQUENCE credit_entry_seq": "USAGE"},
        ),
        # The investigator reads the ledger's table, never its API: it holds no token that could credit.
        _reader({"TABLE credits": "SELECT"}),
    ),
    "posting": (
        RuntimeRole(
            "app",
            "POSTING_DB_PASSWORD",
            {
                "TABLE posting": "SELECT, INSERT",
                "TABLE outbox": "SELECT, INSERT",
                "SEQUENCE outbox_id_seq": "USAGE",
                # ADR-0016: the posting service parks events and the retry worker moves them on. Neither can
                # delete a parked event or rewrite its original bytes.
                "TABLE parked_event": "SELECT, INSERT, UPDATE (status, attempts, transient_failures, next_attempt_at,"
                " claimed_by, lease_until, error_class, last_error, first_failed_at, last_failed_at, done_at, dead_at)",
                "SEQUENCE parked_event_id_seq": "USAGE",
                "TABLE skipped_event": "SELECT, INSERT",  # D10: stale revisions, recorded once, never changed
            },
        ),
        RuntimeRole(
            "relay",
            "RELAY_DB_PASSWORD",
            {
                "TABLE outbox": "SELECT, UPDATE (status, attempts, last_error, next_attempt_at, claimed_by,"
                " lease_until, published_at, dead_at)"
            },
        ),
        _reader(
            {
                "TABLE posting": "SELECT",
                "TABLE outbox": "SELECT",
                "TABLE parked_event": f"SELECT ({_PARKED_READABLE})",
                "TABLE skipped_event": "SELECT",
            }
        ),
    ),
    # RFC-0002, ADR-0019: stored evidence. The services may only add log lines and alert evaluations. They can't
    # read them back, change them or delete them, and can't touch the change feed, questions or runbooks.
    "ops": (
        RuntimeRole(
            "app",
            "OPS_DB_PASSWORD",
            {
                "TABLE log_event": "INSERT",
                "SEQUENCE log_event_id_seq": "USAGE",
                "TABLE alert_evaluation": "INSERT",
                "SEQUENCE alert_evaluation_id_seq": "USAGE",
            },
        ),
        _reader(
            {
                "TABLE log_event": "SELECT",
                "TABLE change_event": "SELECT",
                "TABLE member_question": "SELECT",
                "TABLE alert_evaluation": "SELECT",
                "TABLE runbook_section": "SELECT",
            }
        ),
    ),
}

# In order, without repeats: several roles may share one variable.
PASSWORD_VARIABLES = tuple(dict.fromkeys(role.password_variable for roles in RUNTIME_ROLES.values() for role in roles))


@dataclass(frozen=True)
class Database:
    base: str  # ledger | posting | ops
    prefix: str = ""

    def __post_init__(self) -> None:
        if not _PREFIX.fullmatch(self.prefix):
            raise ValueError("prefix must be lowercase letters and underscores, at most 16")
        if self.base not in RUNTIME_ROLES:
            raise ValueError(f"unknown database {self.base!r}")

    @property
    def name(self) -> str:
        return f"{self.prefix}{self.base}"

    @property
    def owner(self) -> str:
        return f"{self.prefix}{self.base}_owner"

    @property
    def roles(self) -> tuple[RuntimeRole, ...]:
        return RUNTIME_ROLES[self.base]

    def role_name(self, suffix: str = "app") -> str:
        if suffix not in {role.suffix for role in self.roles}:
            raise ValueError(f"{self.base} has no {suffix!r} role")
        return f"{self.prefix}{self.base}_{suffix}"

    @property
    def runtime(self) -> str:
        """The main service's role (`<db>_app`)."""
        return self.role_name("app")

    @property
    def password_variable(self) -> str:
        return self.roles[0].password_variable


CONNECT_TIMEOUT_SECONDS = 10


def loopback(host: str | None) -> str:
    """`localhost` becomes 127.0.0.1. On Windows `localhost` resolves to ::1 first, and Docker Desktop accepts ::1
    and then never answers, so libpq waited forever (found in M2: the first integration run hung). The stack binds
    127.0.0.1 only, so the IPv4 address is the one that works."""
    return "127.0.0.1" if host in (None, "", "localhost") else host


def runtime_url(database: Database, password: str, host: str = "localhost", port: int = 5432, role: str = "app") -> URL:
    """A connection URL for a runtime role. A URL object, so the password never sits in a string we might log."""
    return URL.create(
        "postgresql+psycopg",
        username=database.role_name(role),
        password=password,
        host=loopback(host),
        port=port,
        database=database.name,
        query={"connect_timeout": str(CONNECT_TIMEOUT_SECONDS)},
    )
