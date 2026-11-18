"""Smoke test of the running ledger container (`docker compose --profile core`), over HTTP.

Needs TEST_LEDGER_URL and TEST_LEDGER_TOKEN (scripts\\test_integration.ps1 maps them from LEDGER_API_URL and
LEDGER_API_TOKEN without printing them). It writes one synthetic credit under a unique `smoke-` key to the stack's
ledger database, which is how a smoke test proves the service and its runtime role work end to end.
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

pytestmark = pytest.mark.postgres  # the container's whole point is its database; REQUIRE_MARKERS covers it


@pytest.fixture(scope="module")
def ledger() -> tuple[str, str]:
    url, token = os.environ.get("TEST_LEDGER_URL"), os.environ.get("TEST_LEDGER_TOKEN")
    if not (url and token):
        pytest.skip(
            "TEST_LEDGER_URL / TEST_LEDGER_TOKEN not set: run scripts\\stack.ps1 up, then scripts\\test_integration.ps1"
        )
    return url.replace("://localhost", "://127.0.0.1"), token


def test_the_running_ledger_credits_once_and_refuses_a_wrong_token(ledger):
    url, token = ledger
    key = f"smoke-{uuid.uuid4()}"
    body = {"member_number": "GR-09999", "stay_id": "ML-9999", "points": 10, "correlation_id": f"corr-{key}"}
    with httpx.Client(base_url=url, timeout=10) as client:
        assert client.get("/readyz").json() == {"status": "ready"}
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": key}
        first = client.post("/v1/credits", json=body, headers=headers)
        again = client.post("/v1/credits", json=body, headers=headers)
        assert (first.status_code, again.status_code) == (201, 200)
        assert first.json()["entry_id"] == again.json()["entry_id"]
        assert client.get(f"/v1/credits/{key}", headers=headers).json()["points"] == 10
        wrong = client.post("/v1/credits", json=body, headers={**headers, "Authorization": "Bearer not-the-token-1"})
        assert wrong.status_code == 401
        assert token not in wrong.text and token not in first.text
