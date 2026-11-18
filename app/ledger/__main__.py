"""Run the ledger mock: `python -m app.ledger` (in Docker Compose: the `ledger` service).

Settings come from the environment (a local `.env` is loaded if present; nothing is printed):
- `LEDGER_API_TOKEN` (required), `LEDGER_TOKEN_EXPIRES_AT`, `LEDGER_LATENCY_MS`, `LEDGER_RATE_PER_SEC`,
  `LEDGER_BURST`
- `LEDGER_DB_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`, `DB_PREFIX`: it connects as the runtime role `ledger_app`,
  never as the owner or the superuser
- `LEDGER_CONTROL_ENABLED=true` adds `/control/settings` for the local stack. `PUBLIC_DEMO_MODE=true` always turns
  it off
- `LEDGER_HOST` / `LEDGER_PORT` (default 127.0.0.1:8020)
"""

from __future__ import annotations

import os

import uvicorn
from dotenv import load_dotenv
from sqlalchemy import create_engine

from app.db.roles import Database, runtime_url
from app.ledger.api import create_app
from app.ledger.core import LedgerSettings
from app.ledger.store import PostgresCreditStore


def main() -> None:
    load_dotenv(override=False)
    env = os.environ
    database = Database("ledger", env.get("DB_PREFIX", ""))
    url = runtime_url(
        database,
        env.get("LEDGER_DB_PASSWORD", ""),
        host=env.get("POSTGRES_HOST", "localhost"),
        port=int(env.get("POSTGRES_PORT", "5432")),
    )
    control = env.get("LEDGER_CONTROL_ENABLED", "false") == "true" and env.get("PUBLIC_DEMO_MODE", "false") != "true"
    app = create_app(
        PostgresCreditStore(create_engine(url, pool_pre_ping=True)),
        LedgerSettings.from_env(env),
        control_enabled=control,
    )
    uvicorn.run(
        app,
        host=env.get("LEDGER_HOST", "127.0.0.1"),
        port=int(env.get("LEDGER_PORT", "8020")),
        timeout_graceful_shutdown=10,  # finish in-flight requests on SIGTERM (DEL-01)
    )


if __name__ == "__main__":
    main()
