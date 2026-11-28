"""Stored evidence from the three databases, read as the `*_investigator` roles. Every query is a bounded SELECT.

The queries are fixed text with bound parameters. Nothing here builds SQL from what it read, so text found in a log
line or an error detail can't become a query.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.evidence.model import Evidence, evidence

DEFAULT_LIMIT = 200
MAX_LIMIT = 1000

# name -> (database, kind, SQL, id column, time column). `:since` and `:limit` are always bound.
QUERIES: dict[str, tuple[str, str, str, str, str | None]] = {
    "postings": (
        "posting",
        "posting",
        "SELECT event_id, stay_id, revision, member_number, stay_points, credited_points, ledger_entry_id,"
        " correlation_id, posted_at FROM posting WHERE posted_at >= :since ORDER BY posted_at, event_id LIMIT :limit",
        "event_id",
        "posted_at",
    ),
    "outbox": (
        "posting",
        "outbox",
        "SELECT id, topic, message_key, status, attempts, last_error, created_at, published_at, dead_at"
        " FROM outbox WHERE created_at >= :since ORDER BY id LIMIT :limit",
        "id",
        "created_at",
    ),
    "parked": (
        "posting",
        "parked",
        "SELECT id, event_id, member_number, stay_id, revision, source_topic, source_partition, source_offset,"
        " status, attempts, transient_failures, error_class, last_error, raw_headers ->> 'correlation_id' AS"
        " correlation_id, first_failed_at, last_failed_at, parked_at, done_at, dead_at"
        " FROM parked_event WHERE parked_at >= :since ORDER BY id LIMIT :limit",
        "id",
        "parked_at",
    ),
    "skipped": (
        "posting",
        "skipped",
        "SELECT event_id, stay_id, revision, member_number, reason, latest_revision, correlation_id, skipped_at"
        " FROM skipped_event WHERE skipped_at >= :since ORDER BY skipped_at, event_id LIMIT :limit",
        "event_id",
        "skipped_at",
    ),
    "credits": (
        "ledger",
        "credit",
        "SELECT entry_id, idempotency_key, member_number, stay_id, points, correlation_id, created_at"
        " FROM credits WHERE created_at >= :since ORDER BY created_at, entry_id LIMIT :limit",
        "entry_id",
        "created_at",
    ),
    "logs": (
        "ops",
        "log",
        "SELECT id, logged_at, service, level, logger, message, correlation_id, trace_id, event_id"
        " FROM log_event WHERE logged_at >= :since AND level IN ('WARNING', 'ERROR', 'CRITICAL')"
        " ORDER BY id LIMIT :limit",
        "id",
        "logged_at",
    ),
    "lifecycle_logs": (  # the INFO lines that mark a start, a stop or a rebalance; request lines are left out
        "ops",
        "log",
        "SELECT id, logged_at, service, level, logger, message, correlation_id, trace_id, event_id"
        " FROM log_event WHERE logged_at >= :since AND level = 'INFO'"
        " AND (message LIKE '%service started' OR message LIKE '%service stopped' OR message LIKE 'partitions %')"
        " ORDER BY id LIMIT :limit",
        "id",
        "logged_at",
    ),
    "changes": (
        "ops",
        "change",
        "SELECT id, changed_at, service, setting, old_value, new_value, source"
        " FROM change_event WHERE changed_at >= :since ORDER BY id LIMIT :limit",
        "id",
        "changed_at",
    ),
    "questions": (
        "ops",
        "question",
        "SELECT id, asked_at, member_number, stay_id, question"
        " FROM member_question WHERE asked_at >= :since ORDER BY id LIMIT :limit",
        "id",
        "asked_at",
    ),
    "alerts": (
        "ops",
        "alert",
        "SELECT id, evaluated_at, rule, state, signals, missing"
        " FROM alert_evaluation WHERE evaluated_at >= :since ORDER BY id LIMIT :limit",
        "id",
        "evaluated_at",
    ),
}


class EvidenceStore:
    """`engines` maps posting, ledger and ops to SQLAlchemy engines that log in as the read-only roles."""

    def __init__(self, engines: Mapping[str, Any]) -> None:
        missing = {"posting", "ledger", "ops"} - set(engines)
        if missing:
            raise ValueError(f"an engine is needed for each of: {sorted(missing)}")
        self.engines = engines

    def read(self, name: str, since: datetime, limit: int = DEFAULT_LIMIT) -> tuple[list[Evidence], bool]:
        """(the items, whether the limit was hit). One extra row is fetched to know that there were more."""
        from sqlalchemy import text

        if name not in QUERIES:
            raise ValueError(f"unknown evidence read {name!r}")
        if not 1 <= limit <= MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
        database, kind, sql, id_column, time_column = QUERIES[name]
        with self.engines[database].connect() as conn:
            rows = [dict(row._mapping) for row in conn.execute(text(sql), {"since": since, "limit": limit + 1})]
        more = len(rows) > limit
        items = []
        for row in rows[:limit]:
            key = row.pop(id_column)
            at = row.pop(time_column) if time_column else None
            data = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in row.items()}
            items.append(evidence(kind, str(key), at, **data))
        return items, more


def engines_from_env(env: Mapping[str, str]) -> dict[str, Any]:
    """Engines for the three read-only roles, from INVESTIGATOR_DB_PASSWORD. Never an owner or a service role."""
    from sqlalchemy import create_engine

    from app.db.roles import INVESTIGATOR, RUNTIME_ROLES, Database, runtime_url

    password = env.get("INVESTIGATOR_DB_PASSWORD", "")
    if not password:
        raise ValueError("INVESTIGATOR_DB_PASSWORD is not set")
    host, port, prefix = (
        env.get("POSTGRES_HOST", "localhost"),
        int(env.get("POSTGRES_PORT", "5432")),
        env.get("DB_PREFIX", ""),
    )
    return {
        base: create_engine(
            runtime_url(Database(base, prefix), password, host=host, port=port, role=INVESTIGATOR), pool_pre_ping=True
        )
        for base in RUNTIME_ROLES
    }
