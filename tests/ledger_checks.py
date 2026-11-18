"""The "exactly one credit per event" check every pipeline test ends with (RFC-0001 test plan).

It reads the ledger database directly, not the API, so it sees what is really stored.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import Connection, func, select

from app.ledger.schema import credits


def credit_problems(conn: Connection, expected: dict[str, int]) -> list[str]:
    """Problems with the stored credits, compared with `expected` (idempotency key -> points). Empty means correct."""
    rows = conn.execute(
        select(credits.c.idempotency_key, func.count(), func.sum(credits.c.points)).group_by(credits.c.idempotency_key)
    ).all()
    stored = {key: (count, total) for key, count, total in rows}
    problems = [f"{key}: {count} credits" for key, (count, _) in stored.items() if count != 1]
    problems += [f"{key}: no credit" for key in expected if key not in stored]
    problems += [f"{key}: unexpected credit" for key in stored if key not in expected]
    problems += [
        f"{key}: {stored[key][1]} points, expected {points}"
        for key, points in expected.items()
        if key in stored and stored[key][1] != points
    ]
    return sorted(problems)


def keys(prefix: str, n: int) -> Iterable[str]:
    return (f"{prefix}-{i:04d}" for i in range(n))
