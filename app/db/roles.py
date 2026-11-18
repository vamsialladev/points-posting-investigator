"""Who may connect to which database, and with which rights (RFC-0001 D9, Stage 9's owner/runtime lesson).

Each database has two roles:
- an **owner** that owns the tables and runs migrations. It has NOLOGIN: the bootstrap connects as the Postgres
  superuser and runs migrations under `SET ROLE <owner>`, so no service ever holds an owner password.
- a **runtime** role with only the rights its service needs. The ledger's runtime role can't UPDATE or DELETE a
  credit, so a second credit or an edited one is refused by Postgres even if application code is wrong.

A prefix (`test_`) gives the test suite its own roles and databases, so tests never touch the running stack.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.engine import URL

_PREFIX = re.compile(r"[a-z_]{0,16}")


@dataclass(frozen=True)
class Database:
    base: str  # posting | ledger
    prefix: str = ""

    def __post_init__(self) -> None:
        if not _PREFIX.fullmatch(self.prefix):
            raise ValueError("prefix must be lowercase letters and underscores, at most 16")
        if self.base not in GRANTS:
            raise ValueError(f"unknown database {self.base!r}")

    @property
    def name(self) -> str:
        return f"{self.prefix}{self.base}"

    @property
    def owner(self) -> str:
        return f"{self.prefix}{self.base}_owner"

    @property
    def runtime(self) -> str:
        return f"{self.prefix}{self.base}_app"

    @property
    def password_variable(self) -> str:
        return f"{self.base.upper()}_DB_PASSWORD"


# Runtime rights, table by table. Anything not listed is refused. tests/test_db_roles.py checks each one against the
# real database, both what is allowed and what is not.
GRANTS: dict[str, dict[str, str]] = {
    "ledger": {
        "TABLE credits": "SELECT, INSERT",
        "SEQUENCE credit_entry_seq": "USAGE",
    },
    "posting": {
        "TABLE posting": "SELECT, INSERT",
        "TABLE outbox": "SELECT, INSERT, UPDATE (published_at, attempts, last_error)",
        "SEQUENCE outbox_id_seq": "USAGE",
    },
}


CONNECT_TIMEOUT_SECONDS = 10


def loopback(host: str | None) -> str:
    """`localhost` becomes 127.0.0.1. On Windows `localhost` resolves to ::1 first, and Docker Desktop accepts ::1
    and then never answers, so libpq waited forever (found in M2: the first integration run hung). The stack binds
    127.0.0.1 only, so the IPv4 address is the one that works."""
    return "127.0.0.1" if host in (None, "", "localhost") else host


def runtime_url(database: Database, password: str, host: str = "localhost", port: int = 5432) -> URL:
    """A connection URL for the runtime role. A URL object, so the password never sits in a string we might log."""
    return URL.create(
        "postgresql+psycopg",
        username=database.runtime,
        password=password,
        host=loopback(host),
        port=port,
        database=database.name,
        query={"connect_timeout": str(CONNECT_TIMEOUT_SECONDS)},
    )
