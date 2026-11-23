"""Create the roles and databases, migrate them, and grant the runtime rights (RFC-0001 D9).

    python -m app.db.bootstrap [--prefix test_] [--reset]

Safe to run again: roles and databases are created only if missing, runtime passwords are set again (so a rotation
in `.env` takes effect), and every runtime grant is revoked and re-granted from `app.db.roles.RUNTIME_ROLES`, so
the rights are always exactly the listed ones. It prints names and steps, never a value.
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
from app.db.roles import CONNECT_TIMEOUT_SECONDS, PASSWORD_VARIABLES, RUNTIME_ROLES, Database, loopback

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
    """REVOKE then GRANT for each object and runtime role, so every role ends with exactly what RUNTIME_ROLES lists."""
    statements = []
    for runtime in database.roles:
        role = sql.Identifier(database.role_name(runtime.suffix))
        for obj, privileges in runtime.grants.items():
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
    """`passwords` maps each RUNTIME_ROLES password variable (LEDGER_DB_PASSWORD, ...) to its value."""
    databases = [Database(base, prefix) for base in RUNTIME_ROLES]
    for variable in PASSWORD_VARIABLES:
        if len(passwords.get(variable, "")) < MIN_PASSWORD:
            raise ValueError(f"{variable} is missing or shorter than {MIN_PASSWORD} characters")

    with psycopg.connect(**conninfo(admin_url), autocommit=True) as conn:
        for database in databases:
            owner = sql.Identifier(database.owner)
            if not _role_exists(conn, database.owner):
                conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(owner))
            for runtime in database.roles:
                name = database.role_name(runtime.suffix)
                if not _role_exists(conn, name):
                    conn.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(name)))
                conn.execute(
                    sql.SQL("ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}").format(
                        sql.Identifier(name), sql.Literal(passwords[runtime.password_variable])
                    )
                )
            if reset:
                conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database.name)))
            if not _database_exists(conn, database.name):
                conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(database.name), owner))
            conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database.name)))
            for runtime in database.roles:
                conn.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(database.name), sql.Identifier(database.role_name(runtime.suffix))
                    )
                )

    for database in databases:
        with psycopg.connect(**conninfo(admin_url, database.name), autocommit=True) as conn:
            conn.execute(sql.SQL("ALTER SCHEMA public OWNER TO {}").format(sql.Identifier(database.owner)))
            conn.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
            for runtime in database.roles:
                conn.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                        sql.Identifier(database.role_name(runtime.suffix))
                    )
                )
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
    passwords = {variable: os.environ.get(variable, "") for variable in PASSWORD_VARIABLES}
    for database in bootstrap(url, passwords, prefix=args.prefix, reset=args.reset):
        roles = ", ".join(database.role_name(runtime.suffix) for runtime in database.roles)
        print(f"{database.name}: roles {database.owner} (no login), {roles}; migrated; grants applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
