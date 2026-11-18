"""The ledger mock's HTTP API (RFC-0001 D11). Simulated system of record, synthetic data.

- `POST /v1/credits` with an `Idempotency-Key` header:
  - 201: a new credit
  - 200: the same key and request again, so the same entry comes back with `replayed: true`
  - 409: the same key with a different request, which carries the existing entry ID (something WAS applied)
  - 401: a missing, invalid or expired token
  - 429: over the rate limit, with `Retry-After`
- `GET /v1/credits/{key}`: the status lookup (200 or 404).
- `/healthz` (the process is up) and `/readyz` (the database answers).
- `POST /control/settings`: latency, rate limit and token expiry, so the M3 triggers can break the ledger on purpose.
  It only exists when the app is built with `control_enabled`, needs the token (expiry ignored, so an expired
  token can be repaired) and never shows the token.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.ledger.core import (
    MEMBER_PATTERN,
    STAY_PATTERN,
    CreditRequest,
    LedgerSettings,
    TokenBucket,
    bearer,
    token_problem,
)
from app.ledger.store import Credit, CreditStore, IdempotencyConflict

MAX_POINTS = 1_000_000


class CreditBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    member_number: str = Field(pattern=MEMBER_PATTERN)
    stay_id: str = Field(pattern=STAY_PATTERN)
    points: int = Field(ge=-MAX_POINTS, le=MAX_POINTS)  # negative only for a correction's difference (D10)
    correlation_id: str = Field(min_length=1, max_length=100)


class CreditOut(BaseModel):
    entry_id: str
    idempotency_key: str
    member_number: str
    stay_id: str
    points: int
    correlation_id: str
    created_at: datetime
    replayed: bool


class ControlBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latency_ms: int | None = Field(default=None, ge=0, le=120_000)
    rate_per_sec: float | None = Field(default=None, gt=0, le=10_000)
    burst: int | None = Field(default=None, ge=1, le=10_000)
    token_expires_at: datetime | None = None
    clear_token_expiry: bool = False


class LedgerState:
    """The settings and the rate limiter, swapped together under one lock."""

    def __init__(self, settings: LedgerSettings, monotonic: Callable[[], float]) -> None:
        self._lock = threading.Lock()
        self._monotonic = monotonic
        self.settings = settings
        self.bucket = TokenBucket(settings.rate_per_sec, settings.burst, monotonic)

    def update(self, **changes: object) -> LedgerSettings:
        with self._lock:
            self.settings = self.settings.changed(**changes)
            if "rate_per_sec" in changes or "burst" in changes:
                self.bucket = TokenBucket(self.settings.rate_per_sec, self.settings.burst, self._monotonic)
            return self.settings


def _out(credit: Credit, replayed: bool) -> CreditOut:
    return CreditOut(
        entry_id=credit.entry_id,
        idempotency_key=credit.idempotency_key,
        member_number=credit.member_number,
        stay_id=credit.stay_id,
        points=credit.points,
        correlation_id=credit.correlation_id,
        created_at=credit.created_at,
        replayed=replayed,
    )


def create_app(
    store: CreditStore,
    settings: LedgerSettings,
    *,
    control_enabled: bool = False,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> FastAPI:
    app = FastAPI(title="Ledger mock (simulated, synthetic data)", docs_url=None, redoc_url=None)
    state = LedgerState(settings, monotonic)
    app.state.ledger = state

    def _authorize(authorization: str | None, allow_expired: bool) -> None:
        current = state.settings
        problem = token_problem(
            bearer(authorization), current.token, None if allow_expired else current.token_expires_at, now()
        )
        if problem:
            raise HTTPException(401, detail={"error": f"token_{problem}"}, headers={"WWW-Authenticate": "Bearer"})

    def authorized(authorization: Annotated[str | None, Header()] = None) -> None:
        _authorize(authorization, allow_expired=False)

    def throttled() -> None:
        wait = state.bucket.take()
        if wait:
            raise HTTPException(
                429, detail={"error": "rate_limited"}, headers={"Retry-After": str(max(1, math.ceil(wait)))}
            )
        if state.settings.latency_ms:
            sleep(state.settings.latency_ms / 1000)

    guarded = [Depends(authorized), Depends(throttled)]  # auth first, then the rate limit and latency

    @app.post("/v1/credits", status_code=201, response_model=CreditOut, dependencies=guarded)
    def post_credit(
        body: CreditBody,
        response: Response,
        idempotency_key: Annotated[str, Header(min_length=1, max_length=200)],
    ) -> Any:
        request = CreditRequest(body.member_number, body.stay_id, body.points, body.correlation_id)
        try:
            credit, created = store.credit(idempotency_key, request)
        except IdempotencyConflict as conflict:
            return JSONResponse(
                status_code=409, content={"error": "idempotency_conflict", "entry_id": conflict.existing.entry_id}
            )
        if not created:
            response.status_code = 200
        return _out(credit, replayed=not created)

    @app.get("/v1/credits/{idempotency_key}", response_model=CreditOut, dependencies=guarded)
    def get_credit(idempotency_key: str) -> Any:
        credit = store.lookup(idempotency_key)
        if credit is None:
            raise HTTPException(404, detail={"error": "not_found"})
        return _out(credit, replayed=False)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> Any:
        try:
            store.ping()
        except Exception:  # any database failure means "not ready"; the reason goes to the log, not the reply
            return JSONResponse(status_code=503, content={"status": "database unavailable"})
        return {"status": "ready"}

    if control_enabled:

        @app.post("/control/settings")
        def control(body: ControlBody, authorization: Annotated[str | None, Header()] = None) -> dict[str, object]:
            _authorize(authorization, allow_expired=True)
            changes: dict[str, object] = body.model_dump(exclude_none=True, exclude={"clear_token_expiry"})
            if body.clear_token_expiry:
                changes["token_expires_at"] = None
            return state.update(**changes).public()

    return app
