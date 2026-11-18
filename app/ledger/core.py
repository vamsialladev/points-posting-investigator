"""The ledger mock's rules as pure functions: auth, rate limit, request fingerprint, settings (RFC-0001 D11).

No I/O here, so every rule is unit-tested without a database. The clock is passed in.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

MEMBER_PATTERN = r"^GR-[0-9]{5}$"
STAY_PATTERN = r"^(BR|ML)-[0-9]{4}$"
MIN_TOKEN = 12


@dataclass(frozen=True)
class CreditRequest:
    member_number: str
    stay_id: str
    points: int
    correlation_id: str


def request_hash(idempotency_key: str, request: CreditRequest) -> str:
    """A fingerprint of what was asked. The same key with a different fingerprint is a 409, never a silent replay."""
    body = [idempotency_key, request.member_number, request.stay_id, request.points]
    return hashlib.sha256(json.dumps(body, separators=(",", ":")).encode()).hexdigest()


def token_problem(given: str | None, expected: str, expires_at: datetime | None, now: datetime) -> str | None:
    """None when the bearer token is good; otherwise why not: missing, invalid or expired."""
    if not given:
        return "missing"
    if not hmac.compare_digest(given.encode(), expected.encode()):
        return "invalid"
    if expires_at is not None and now >= expires_at:
        return "expired"
    return None


def bearer(header: str | None) -> str | None:
    if header and header.startswith("Bearer "):
        return header.removeprefix("Bearer ").strip() or None
    return None


class TokenBucket:
    """`rate` tokens a second, up to `burst`. `take()` returns 0.0 when allowed, else seconds until a token is free."""

    def __init__(self, rate: float, burst: int, clock: Callable[[], float]) -> None:
        if rate <= 0 or burst < 1:
            raise ValueError("rate must be > 0 and burst >= 1")
        self.rate, self.burst, self._clock = rate, burst, clock
        self._tokens = float(burst)
        self._last = clock()
        self._lock = threading.Lock()

    def take(self) -> float:
        with self._lock:
            now = self._clock()
            self._tokens = min(self.burst, self._tokens + (now - self._last) * self.rate)
            self._last = now
            if self._tokens >= 1:
                self._tokens -= 1
                return 0.0
            return (1 - self._tokens) / self.rate


@dataclass(frozen=True)
class LedgerSettings:
    token: str = field(repr=False)  # never in a repr, a log line or a response
    token_expires_at: datetime | None = None
    latency_ms: int = 0
    rate_per_sec: float = 50.0
    burst: int = 100

    def __post_init__(self) -> None:
        if len(self.token) < MIN_TOKEN:
            raise ValueError(f"LEDGER_API_TOKEN must be at least {MIN_TOKEN} characters")
        if not 0 <= self.latency_ms <= 120_000:
            raise ValueError("latency_ms must be between 0 and 120000")

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> LedgerSettings:
        expires = environ.get("LEDGER_TOKEN_EXPIRES_AT", "")
        return cls(
            token=environ.get("LEDGER_API_TOKEN", ""),
            token_expires_at=parse_time(expires) if expires else None,
            latency_ms=int(environ.get("LEDGER_LATENCY_MS", "0")),
            rate_per_sec=float(environ.get("LEDGER_RATE_PER_SEC", "50")),
            burst=int(environ.get("LEDGER_BURST", "100")),
        )

    def public(self) -> dict[str, object]:
        """What the control endpoint shows: everything except the token."""
        return {
            "token_expires_at": self.token_expires_at.isoformat() if self.token_expires_at else None,
            "latency_ms": self.latency_ms,
            "rate_per_sec": self.rate_per_sec,
            "burst": self.burst,
        }

    def changed(self, **changes: object) -> LedgerSettings:
        return replace(self, **changes)  # type: ignore[arg-type]


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("times must include a UTC offset")
    return parsed.astimezone(UTC)
