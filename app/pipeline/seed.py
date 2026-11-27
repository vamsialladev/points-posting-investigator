"""Synthetic members and stays in Stage 9's shapes (RFC-0001 PIPE-09). Simulated people, synthetic data.

- Members: `GR-#####`, tiers Silver / Gold / Platinum, tenant `hg-demo`.
- Stays: `BR-####` (Beach Resort) or `ML-####` (Mountain Lodge), allocated in sequence from `first_stay`, so no two
  stays share an ID. (A shared stay ID would make `UNIQUE(stay_id, revision)` treat the second stay as a duplicate,
  and the ledger would refuse it with a 409.) One property holds 9,999 stay numbers.
- Event IDs come from the seed, so the same seed gives exactly the same events: a rerun is a set of real duplicates.
- Points: 10 per US dollar of room rate only (Stage 9); taxes and fees are carried but don't earn.

Pure functions, no I/O.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.pipeline.producer import build_event

TIERS = ("Silver", "Gold", "Platinum")
TIER_WEIGHTS = (70, 22, 8)
MAX_STAY_NUMBER = 9_999  # BR-#### / ML-####
MAX_MEMBER_NUMBER = 99_999  # GR-#####
FIRST_CHECK_IN = date(2026, 11, 1)


@dataclass(frozen=True)
class Member:
    member_number: str
    tier: str
    tenant: str = "hg-demo"


def members(count: int, seed: int) -> list[Member]:
    """`count` members, GR-00001 upwards, with seeded tiers."""
    if not 1 <= count <= MAX_MEMBER_NUMBER:
        raise ValueError(f"count must be between 1 and {MAX_MEMBER_NUMBER}")
    rng = random.Random(seed)  # noqa: S311 (synthetic data, not security)
    return [Member(f"GR-{n:05d}", rng.choices(TIERS, TIER_WEIGHTS)[0]) for n in range(1, count + 1)]


def _event_id(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def stays(
    count: int,
    seed: int,
    member_count: int = 200,
    first_stay: int = 1,
    occurred_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """`count` original checkouts (revision 1). Stay numbers run from `first_stay`, alternating Beach Resort and
    Mountain Lodge, so the stays are distinct. The same arguments always give the same records, event IDs included."""
    if count < 1:
        raise ValueError("count must be at least 1")
    per_property = (count + 1) // 2
    last = first_stay + per_property - 1
    if first_stay < 1 or last > MAX_STAY_NUMBER:
        raise ValueError(f"stays {first_stay}..{last} per property don't fit BR-/ML-#### (max {MAX_STAY_NUMBER})")
    rng = random.Random(seed)  # noqa: S311 (synthetic data, not security)
    people = members(member_count, seed)
    when = occurred_at or datetime(2026, 11, 20, tzinfo=UTC)
    records = []
    for i in range(count):
        prefix = "BR" if i % 2 == 0 else "ML"
        number = first_stay + i // 2
        nights = rng.randint(1, 5)
        records.append(
            build_event(
                member_number=rng.choice(people).member_number,
                stay_id=f"{prefix}-{number:04d}",
                check_in=FIRST_CHECK_IN + timedelta(days=rng.randint(0, 14)),
                nights=nights,
                room_rate_cents=rng.randint(9_000, 60_000) * nights,
                taxes_cents=rng.randint(0, 6_000),
                fees_cents=rng.choice([0, 2_500, 3_000]),
                event_id=_event_id(rng),
                occurred_at=when,
            )
        )
    return records


def correction_of(record: dict[str, Any], rng: random.Random, revision: int = 2) -> dict[str, Any]:
    """A correction of a checkout: the same stay and member, a higher revision, a changed room rate, a new event ID."""
    factor = rng.choice([0.8, 0.9, 1.1, 1.25])
    return build_event(
        member_number=record["member_number"],
        stay_id=record["stay_id"],
        property=record["property"],
        check_in=record["check_in"],
        nights=record["nights"],
        room_rate_cents=int(record["room_rate_cents"] * factor),
        taxes_cents=record["taxes_cents"],
        fees_cents=record["fees_cents"],
        revision=revision,
        event_id=_event_id(rng),
        occurred_at=record["occurred_at"],
    )
