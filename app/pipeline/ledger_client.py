"""The posting service's client for the ledger mock (RFC-0001 D5, D11; Stage 9's write-path lessons).

- 201 / 200: credited, or the same credit replayed. Either way the entry comes back.
- **409:** the key was already used for a different request. Something was applied under it, so it's never "safe to
  retry": permanent.
- **401** (expired or rotated token), **429** (rate limited), **5xx**, connection errors: transient.
- Other **4xx**: the ledger refuses the request. Permanent.
- **Timeout:** the credit may have landed. Look it up `lookups` times, `settle_seconds` apart (one "not found" isn't
  proof) before calling it transient. A credit found with different points is a conflict, not a success.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class Credited:
    entry_id: str
    replayed: bool


class LedgerTransient(Exception):
    def __init__(self, reason: str, retry_after: float | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_after = retry_after


class LedgerPermanent(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


class LedgerClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 5.0,
        settle_seconds: float = 0.5,
        lookups: int = 2,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url.replace("://localhost", "://127.0.0.1"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
            transport=transport,
        )
        self._settle, self._lookups, self._sleep = settle_seconds, lookups, sleep

    def close(self) -> None:
        self._http.close()

    def credit(self, key: str, member_number: str, stay_id: str, points: int, correlation_id: str) -> Credited:
        body = {"member_number": member_number, "stay_id": stay_id, "points": points, "correlation_id": correlation_id}
        try:
            response = self._http.post("/v1/credits", json=body, headers={"Idempotency-Key": key})
        except httpx.TimeoutException:
            return self._after_timeout(key, points)
        except httpx.TransportError as exc:
            raise LedgerTransient("unreachable") from exc
        return self._classify(response)

    def _classify(self, response: httpx.Response) -> Credited:
        status = response.status_code
        if status in (200, 201):
            data: dict[str, Any] = response.json()
            return Credited(str(data["entry_id"]), status == 200)
        if status == 409:
            raise LedgerPermanent("idempotency_conflict", str(response.json().get("entry_id", "")))
        if status == 401:
            raise LedgerTransient("unauthorized")
        if status == 429:
            retry_after = response.headers.get("Retry-After")
            raise LedgerTransient("rate_limited", float(retry_after) if retry_after else None)
        if status >= 500:
            raise LedgerTransient(f"unavailable_{status}")
        raise LedgerPermanent(f"rejected_{status}")

    def _after_timeout(self, key: str, points: int) -> Credited:
        for attempt in range(self._lookups):
            if attempt:
                self._sleep(self._settle)
            try:
                response = self._http.get(f"/v1/credits/{key}")
            except httpx.TransportError:
                continue
            if response.status_code == 200:
                found = response.json()
                if int(found["points"]) != points:
                    raise LedgerPermanent("idempotency_conflict", str(found["entry_id"]))
                return Credited(str(found["entry_id"]), True)
        self._sleep(self._settle)
        raise LedgerTransient("timeout_not_found")
