"""An in-memory CreditStore with the same contract as PostgresCreditStore, for offline API tests.

The real store's behaviour (constraint, race, roles) is tested against real Postgres in tests/test_ledger_postgres.py;
this fake only lets the HTTP rules be tested without a database.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.ledger.core import CreditRequest, request_hash
from app.ledger.store import Credit, IdempotencyConflict


class MemoryCreditStore:
    def __init__(self) -> None:
        self.rows: dict[str, Credit] = {}
        self.healthy = True

    def credit(self, idempotency_key: str, request: CreditRequest) -> tuple[Credit, bool]:
        fingerprint = request_hash(idempotency_key, request)
        existing = self.rows.get(idempotency_key)
        if existing is not None:
            if existing.request_hash != fingerprint:
                raise IdempotencyConflict(existing)
            return existing, False
        credit = Credit(
            entry_id=f"L-{len(self.rows) + 1:07d}",
            idempotency_key=idempotency_key,
            request_hash=fingerprint,
            member_number=request.member_number,
            stay_id=request.stay_id,
            points=request.points,
            correlation_id=request.correlation_id,
            created_at=datetime(2026, 11, 17, tzinfo=UTC),
        )
        self.rows[idempotency_key] = credit
        return credit, True

    def lookup(self, idempotency_key: str) -> Credit | None:
        return self.rows.get(idempotency_key)

    def ping(self) -> None:
        if not self.healthy:
            raise ConnectionError("database down (simulated)")
