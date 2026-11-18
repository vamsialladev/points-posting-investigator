"""The ledger mock's pure rules: request fingerprint, token checks, rate limiter, settings (RFC-0001 D11)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.ledger.core import (
    CreditRequest,
    LedgerSettings,
    TokenBucket,
    bearer,
    parse_time,
    request_hash,
    token_problem,
)

NOW = datetime(2026, 11, 17, 12, tzinfo=UTC)
TOKEN = "fake-ledger-token-1"
REQUEST = CreditRequest("GR-00001", "BR-0001", 4500, "corr-1")


def test_the_fingerprint_is_stable_and_covers_what_matters():
    assert request_hash("k1", REQUEST) == request_hash("k1", REQUEST)
    assert request_hash("k1", REQUEST) != request_hash("k2", REQUEST)
    assert request_hash("k1", REQUEST) != request_hash("k1", CreditRequest("GR-00001", "BR-0001", 4501, "corr-1"))
    assert request_hash("k1", REQUEST) != request_hash("k1", CreditRequest("GR-00002", "BR-0001", 4500, "corr-1"))
    # The correlation ID is tracing, not the request: a retry with a new one is still the same credit.
    assert request_hash("k1", REQUEST) == request_hash("k1", CreditRequest("GR-00001", "BR-0001", 4500, "corr-2"))


@pytest.mark.parametrize(
    ("given", "expires", "expected"),
    [
        (TOKEN, None, None),
        (TOKEN, NOW + timedelta(seconds=1), None),
        (TOKEN, NOW, "expired"),
        (None, None, "missing"),
        ("", None, "missing"),
        ("fake-ledger-token-2", None, "invalid"),
    ],
)
def test_token_problem(given, expires, expected):
    assert token_problem(given, TOKEN, expires, NOW) == expected


def test_after_a_rotation_the_old_token_fails():
    # Standing rule 4: prove the old credential fails once it's rotated.
    rotated = "fake-ledger-token-NEW"
    assert token_problem(TOKEN, rotated, None, NOW) == "invalid"
    assert token_problem(rotated, rotated, None, NOW) is None


@pytest.mark.parametrize(
    ("header", "expected"),
    [("Bearer abc", "abc"), ("Bearer  abc ", "abc"), ("Bearer ", None), ("Basic abc", None), (None, None)],
)
def test_bearer(header, expected):
    assert bearer(header) == expected


class FakeClock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def test_token_bucket_allows_a_burst_then_says_how_long_to_wait():
    clock = FakeClock()
    bucket = TokenBucket(rate=2.0, burst=3, clock=clock)
    assert [bucket.take() for _ in range(3)] == [0.0, 0.0, 0.0]
    assert bucket.take() == pytest.approx(0.5)
    clock.t += 0.5
    assert bucket.take() == 0.0
    clock.t += 100  # refills, but never beyond the burst
    assert [bucket.take() for _ in range(4)][-1] > 0


def test_token_bucket_rejects_nonsense():
    with pytest.raises(ValueError):
        TokenBucket(rate=0, burst=1, clock=FakeClock())
    with pytest.raises(ValueError):
        TokenBucket(rate=1, burst=0, clock=FakeClock())


def test_settings_never_show_the_token():
    settings = LedgerSettings(token=TOKEN)
    assert TOKEN not in repr(settings)
    assert TOKEN not in str(settings.public())
    assert set(settings.public()) == {"token_expires_at", "latency_ms", "rate_per_sec", "burst"}


def test_settings_validate():
    with pytest.raises(ValueError, match="at least 12"):
        LedgerSettings(token="short")
    with pytest.raises(ValueError, match="latency_ms"):
        LedgerSettings(token=TOKEN, latency_ms=-1)


def test_settings_from_env():
    settings = LedgerSettings.from_env(
        {
            "LEDGER_API_TOKEN": TOKEN,
            "LEDGER_TOKEN_EXPIRES_AT": "2026-11-18T00:00:00+00:00",
            "LEDGER_LATENCY_MS": "250",
            "LEDGER_RATE_PER_SEC": "5",
            "LEDGER_BURST": "7",
        }
    )
    assert settings.token_expires_at == datetime(2026, 11, 18, tzinfo=UTC)
    assert (settings.latency_ms, settings.rate_per_sec, settings.burst) == (250, 5.0, 7)
    assert LedgerSettings.from_env({"LEDGER_API_TOKEN": TOKEN}).token_expires_at is None
    with pytest.raises(ValueError):
        LedgerSettings.from_env({})  # no token: refuse to start rather than run open


def test_times_need_an_offset():
    with pytest.raises(ValueError, match="UTC offset"):
        parse_time("2026-11-18T00:00:00")
    assert parse_time("2026-11-18T01:00:00+01:00") == datetime(2026, 11, 18, tzinfo=UTC)
