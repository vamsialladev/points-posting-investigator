"""The ledger mock's HTTP contract, offline (in-memory store). The real-Postgres version is test_ledger_postgres.py."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.ledger.api import create_app
from app.ledger.core import LedgerSettings
from tests.fakes import MemoryCreditStore

TOKEN = "fake-ledger-token-1"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BODY = {"member_number": "GR-00001", "stay_id": "BR-0001", "points": 4500, "correlation_id": "corr-1"}
NOW = datetime(2026, 11, 17, 12, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def make(store=None, *, control=False, **settings):
    store = store or MemoryCreditStore()
    sleeps: list[float] = []
    app = create_app(
        store,
        LedgerSettings(token=TOKEN, **settings),
        control_enabled=control,
        now=lambda: NOW,
        monotonic=Clock(),
        sleep=sleeps.append,
    )
    return TestClient(app), store, sleeps


def credit(client, key="evt-1", body=None, headers=None):
    return client.post("/v1/credits", json=body or BODY, headers={**AUTH, "Idempotency-Key": key, **(headers or {})})


def test_a_new_credit_then_a_replay_returns_the_same_entry():
    client, store, _ = make()
    first = credit(client)
    assert first.status_code == 201
    assert first.json()["entry_id"] == "L-0000001" and first.json()["replayed"] is False
    again = credit(client)
    assert again.status_code == 200
    assert again.json()["entry_id"] == "L-0000001" and again.json()["replayed"] is True
    assert len(store.rows) == 1


def test_the_same_key_with_a_different_request_is_a_conflict_naming_what_was_applied():
    client, store, _ = make()
    credit(client)
    conflict = credit(client, body={**BODY, "points": 9999})
    assert conflict.status_code == 409
    assert conflict.json() == {"error": "idempotency_conflict", "entry_id": "L-0000001"}
    assert store.rows["evt-1"].points == 4500


@pytest.mark.parametrize(
    ("headers", "error"),
    [({"Authorization": ""}, "token_missing"), ({"Authorization": "Bearer fake-ledger-token-x"}, "token_invalid")],
)
def test_bad_tokens_are_refused_and_nothing_is_credited(headers, error):
    client, store, _ = make()
    response = credit(client, headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"]["error"] == error
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert store.rows == {}


def test_an_expired_token_is_a_401_for_credits_and_lookups():
    client, store, _ = make(token_expires_at=NOW - timedelta(seconds=1))
    assert credit(client).json()["detail"]["error"] == "token_expired"
    assert client.get("/v1/credits/evt-1", headers=AUTH).status_code == 401
    assert store.rows == {}


def test_after_a_rotation_the_old_token_is_refused():
    client, _, _ = make()
    rotated = TestClient(create_app(MemoryCreditStore(), LedgerSettings(token="fake-ledger-token-NEW")))
    assert credit(client).status_code == 201
    assert credit(rotated).status_code == 401  # the old token against the rotated ledger


@pytest.mark.parametrize(
    "bad",
    [{"member_number": "GR-1"}, {"stay_id": "XX-0001"}, {"points": 10_000_001}, {"correlation_id": ""}, {"x": 1}],
)
def test_invalid_bodies_are_refused(bad):
    client, store, _ = make()
    assert credit(client, body={**BODY, **bad}).status_code == 422
    assert store.rows == {}


def test_an_idempotency_key_is_required():
    client, _, _ = make()
    assert client.post("/v1/credits", json=BODY, headers=AUTH).status_code == 422


def test_over_the_rate_limit_is_a_429_with_retry_after():
    client, store, _ = make(rate_per_sec=1.0, burst=2)
    assert [credit(client, key=f"evt-{n}").status_code for n in range(2)] == [201, 201]
    limited = credit(client, key="evt-9")
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "1"
    assert "evt-9" not in store.rows


def test_latency_is_applied_before_the_credit():
    client, _, sleeps = make(latency_ms=250)
    credit(client)
    assert sleeps == [0.25]


def test_status_lookup():
    client, _, _ = make()
    assert client.get("/v1/credits/evt-1", headers=AUTH).status_code == 404
    credit(client)
    found = client.get("/v1/credits/evt-1", headers=AUTH)
    assert found.status_code == 200 and found.json()["entry_id"] == "L-0000001"


def test_health_and_readiness():
    client, store, _ = make()
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").status_code == 200
    store.healthy = False
    not_ready = client.get("/readyz")
    assert not_ready.status_code == 503
    assert "simulated" not in not_ready.text  # the reason stays out of the reply
    assert client.get("/healthz").status_code == 200


def test_the_control_endpoint_does_not_exist_unless_enabled():
    client, _, _ = make()
    assert client.post("/control/settings", json={"latency_ms": 5}, headers=AUTH).status_code == 404


def test_control_changes_settings_needs_the_token_and_never_returns_it():
    client, _, sleeps = make(control=True)
    assert client.post("/control/settings", json={"latency_ms": 5}).status_code == 401
    changed = client.post("/control/settings", json={"latency_ms": 5, "rate_per_sec": 3, "burst": 4}, headers=AUTH)
    assert changed.status_code == 200
    assert changed.json() == {"token_expires_at": None, "latency_ms": 5, "rate_per_sec": 3.0, "burst": 4}
    assert TOKEN not in changed.text
    credit(client)
    assert sleeps == [0.005]


def test_control_can_expire_the_token_and_repair_it():
    # M3's "expired credential" trigger and its reset both go through here.
    client, _, _ = make(control=True)
    expired = (NOW - timedelta(minutes=1)).isoformat()
    assert client.post("/control/settings", json={"token_expires_at": expired}, headers=AUTH).status_code == 200
    assert credit(client).status_code == 401
    repaired = client.post("/control/settings", json={"clear_token_expiry": True}, headers=AUTH)
    assert repaired.json()["token_expires_at"] is None
    assert credit(client).status_code == 201


def test_control_refuses_unknown_or_out_of_range_settings():
    client, _, _ = make(control=True)
    assert client.post("/control/settings", json={"token": "x" * 20}, headers=AUTH).status_code == 422
    assert client.post("/control/settings", json={"latency_ms": -1}, headers=AUTH).status_code == 422
