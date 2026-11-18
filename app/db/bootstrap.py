"""Create the roles and databases, migrate them, and grant the runtime rights (RFC-0001 D9).

    python -m app.db.bootstrap [--prefix test_] [--reset]

Safe to run again: roles and databases are created only if missing, runtime passwords are set again (so a rotation
in `.env` takes effect), and every runtime grant is revoked and re-granted from `app.db.roles.GRANTS`, so the rights
are always exactly the listed ones. It prints names and steps, never a value.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping
from typing import Any

import psycopg
from psycopg import sql
from sqlalchemy.engine import URL

from app.db import migrate
from app.db.roles import CONNECT_TIMEOUT_SECONDS, GRANTS, Database, loopback

MIN_PASSWORD = 8


def conninfo(url: URL, database: str | None = None) -> dict[str, Any]:
    return {
        "host": loopback(url.host),
        "port": url.port or 5432,
        "user": url.username,
        "password": url.password,
        "dbname": database or url.database,
        "connect_timeout": CONNECT_TIMEOUT_SECONDS,  # fail, never hang
    }


def grant_statements(database: Database) -> list[sql.Composed]:
    """REVOKE then GRANT for each object, so the runtime role ends with exactly what GRANTS lists."""
    statements = []
    role = sql.Identifier(database.runtime)
    for obj, privileges in GRANTS[database.base].items():
        kind, name = obj.split(" ", 1)
        target = sql.SQL("{} {}").format(sql.SQL(kind), sql.Identifier(name))
        statements.append(sql.SQL("REVOKE ALL ON {} FROM {}").format(target, role))
        statements.append(sql.SQL("GRANT {} ON {} TO {}").format(sql.SQL(privileges), target, role))
    return statements


def _role_exists(conn: psycopg.Connection[Any], role: str) -> bool:
    return conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone() is not None


def _database_exists(conn: psycopg.Connection[Any], name: str) -> bool:
    return conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone() is not None


def bootstrap(admin_url: URL, passwords: Mapping[str, str], prefix: str = "", reset: bool = False) -> list[Database]:
    databases = [Database(base, prefix) for base in GRANTS]
    for database in databases:
        if len(passwords.get(database.base, "")) < MIN_PASSWORD:
            raise ValueError(f"{database.password_variable} is missing or shorter than {MIN_PASSWORD} characters")

    with psycopg.connect(**conninfo(admin_url), autocommit=True) as conn:
        for database in databases:
            owner, runtime = sql.Identifier(database.owner), sql.Identifier(database.runtime)
            if not _role_exists(conn, database.owner):
                conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(owner))
            if not _role_exists(conn, database.runtime):
                conn.execute(sql.SQL("CREATE ROLE {} LOGIN").format(runtime))
            conn.execute(
                sql.SQL("ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}").format(
                    runtime, sql.Literal(passwords[database.base])
                )
            )
            if reset:
                conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database.name)))
            if not _database_exists(conn, database.name):
                conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(database.name), owner))
            conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database.name)))
            conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database.name), runtime))

    for database in databases:
        with psycopg.connect(**conninfo(admin_url, database.name), autocommit=True) as conn:
            owner, runtime = sql.Identifier(database.owner), sql.Identifier(database.runtime)
            conn.execute(sql.SQL("ALTER SCHEMA public OWNER TO {}").format(owner))
            conn.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
            conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(runtime))
        migrate.upgrade(admin_url, database)
        with psycopg.connect(**conninfo(admin_url, database.name), autocommit=True) as conn:
            for statement in grant_statements(database):
                conn.execute(statement)
    return databases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prefix", default="")
    parser.add_argument("--reset", action="store_true", help="drop and recreate the databases first")
    args = parser.parse_args(argv)
    url = migrate.admin_url_from_env()
    passwords = {base: os.environ.get(Database(base).password_variable, "") for base in GRANTS}
    for database in bootstrap(url, passwords, prefix=args.prefix, reset=args.reset):
        print(f"{database.name}: roles {database.owner} (no login), {database.runtime}; migrated; grants applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
