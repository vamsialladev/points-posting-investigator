"""Alembic, one migration tree per database, run as that database's owner role (RFC-0001 D9).

    python -m app.db.migrate upgrade|downgrade|check|roundtrip [--prefix test_]

It connects as the Postgres superuser from DATABASE_URL, then runs `SET ROLE <owner>`, so every table belongs to the
owner and no service needs an owner password. `check` compares the migrated database with the SQLAlchemy tables
(a migration that drifts from the code fails CI). Nothing here prints a value.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.pool import NullPool

from app.db.roles import CONNECT_TIMEOUT_SECONDS, RUNTIME_ROLES, Database, loopback
from app.ledger.schema import metadata as ledger_metadata
from app.pipeline.tables import metadata as posting_metadata

ROOT = Path(__file__).resolve().parent.parent.parent
TREES: dict[str, tuple[Path, MetaData]] = {
    "ledger": (ROOT / "migrations" / "ledger", ledger_metadata),
    "posting": (ROOT / "migrations" / "posting", posting_metadata),
}


def alembic_config(admin_url: URL, database: Database) -> Config:
    location, metadata = TREES[database.base]
    config = Config()
    config.set_main_option("script_location", str(location))
    # Objects, not ini strings: the URL keeps its password out of any file or log line.
    url = admin_url.set(database=database.name, host=loopback(admin_url.host)).update_query_dict(
        {"connect_timeout": str(CONNECT_TIMEOUT_SECONDS)}
    )
    config.attributes.update(url=url, role=database.owner, metadata=metadata)
    return config


def run_env() -> None:
    """Called from each tree's env.py."""
    from alembic import context  # only importable while Alembic runs a command

    config = context.config
    if context.is_offline_mode():
        raise RuntimeError("offline (SQL script) migrations aren't supported: run against a database")
    engine = create_engine(config.attributes["url"], poolclass=NullPool)
    with engine.connect() as connection:
        # The role name comes from app.db.roles.Database, which only allows [a-z_] prefixes and known bases.
        connection.execute(text(f'SET ROLE "{config.attributes["role"]}"'))
        context.configure(
            connection=connection,
            target_metadata=config.attributes["metadata"],
            compare_server_default=False,  # defaults are written by hand in the migrations
        )
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()


def upgrade(admin_url: URL, database: Database, revision: str = "head") -> None:
    command.upgrade(alembic_config(admin_url, database), revision)


def downgrade(admin_url: URL, database: Database, revision: str = "base") -> None:
    command.downgrade(alembic_config(admin_url, database), revision)


def check(admin_url: URL, database: Database) -> None:
    command.check(alembic_config(admin_url, database))


def admin_url_from_env() -> URL:
    from dotenv import load_dotenv

    load_dotenv(override=False)  # values stay in this process; nothing is printed
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        raise SystemExit("DATABASE_URL is missing: run scripts\\preflight.ps1 -Profile core")
    return make_url(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["upgrade", "downgrade", "check", "roundtrip"])
    parser.add_argument("--prefix", default="")
    args = parser.parse_args(argv)
    url = admin_url_from_env()
    for base in RUNTIME_ROLES:
        database = Database(base, args.prefix)
        if args.action in ("upgrade", "roundtrip"):
            upgrade(url, database)
        if args.action in ("downgrade", "roundtrip"):
            downgrade(url, database)
        if args.action == "roundtrip":
            upgrade(url, database)
        if args.action in ("check", "roundtrip"):
            check(url, database)
        print(f"{database.name}: {args.action} ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
