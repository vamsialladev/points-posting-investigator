"""Where credits live. `PostgresCreditStore` is the real one; the API depends only on the `CreditStore` protocol.

A credit is written with `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING`. When two requests race on one key,
Postgres makes the second wait for the first, then inserts nothing: the second request reads the first row back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import Engine, select, text
from sqlalchemy.dialects.postgresql import insert

from app.ledger.core import CreditRequest, request_hash
from app.ledger.schema import credits


@dataclass(frozen=True)
class Credit:
    entry_id: str
    idempotency_key: str
    request_hash: str
    member_number: str
    stay_id: str
    points: int
    correlation_id: str
    created_at: datetime


class IdempotencyConflict(Exception):
    """The key was already used for a different request. Something WAS applied under it: never "safe to retry"."""

    def __init__(self, existing: Credit) -> None:
        super().__init__("idempotency key reused with a different request")
        self.existing = existing


class CreditStore(Protocol):
    def credit(self, idempotency_key: str, request: CreditRequest) -> tuple[Credit, bool]:
        """Returns the credit and whether this call created it (False = a replay of the same request)."""
        ...

    def lookup(self, idempotency_key: str) -> Credit | None: ...

    def ping(self) -> None: ...


_COLUMNS = [credits.c[name] for name in Credit.__dataclass_fields__]


class PostgresCreditStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def credit(self, idempotency_key: str, request: CreditRequest) -> tuple[Credit, bool]:
        fingerprint = request_hash(idempotency_key, request)
        statement = (
            insert(credits)
            .values(
                idempotency_key=idempotency_key,
                request_hash=fingerprint,
                member_number=request.member_number,
                stay_id=request.stay_id,
                points=request.points,
                correlation_id=request.correlation_id,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(*_COLUMNS)
        )
        with self.engine.begin() as conn:
            row = conn.execute(statement).first()
        if row is not None:
            return Credit(**row._mapping), True
        existing = self.lookup(idempotency_key)
        if existing is None:  # the racing insert rolled back; the caller retries the whole request
            raise RuntimeError("credit neither inserted nor found; retry")
        if existing.request_hash != fingerprint:
            raise IdempotencyConflict(existing)
        return existing, False

    def lookup(self, idempotency_key: str) -> Credit | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(*_COLUMNS).where(credits.c.idempotency_key == idempotency_key)).first()
        return Credit(**row._mapping) if row is not None else None

    def ping(self) -> None:
        with self.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
