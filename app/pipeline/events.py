"""`stay.checked_out` events: validation, points, and the ledger's business key (RFC-0001 B1, ADR-0015).

Pure functions, no I/O. The posting service dead-letters an event these refuse, with `InvalidEvent.code` as its error
class.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

SUPPORTED_SCHEMA_VERSIONS = frozenset({"1"})
TENANT = "hg-demo"
PROPERTIES = {"beach-resort": "BR", "mountain-lodge": "ML"}  # property -> stay ID prefix (Stage 9's shapes)
MEMBER = re.compile(r"GR-[0-9]{5}")
STAY = re.compile(r"(BR|ML)-[0-9]{4}")
POINTS_PER_DOLLAR = 10


class InvalidEvent(Exception):
    """An event that can never be posted. `code`: schema, schema_version, invalid_field, unsupported_revision."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class StayEvent:
    event_id: str
    occurred_at: datetime
    tenant: str
    property: str
    stay_id: str
    member_number: str
    revision: int
    check_in: date
    check_out: date
    nights: int
    room_rate_cents: int
    taxes_cents: int
    fees_cents: int
    currency: str
    correlation_id: str


def _require(condition: bool, detail: str) -> None:
    if not condition:
        raise InvalidEvent("invalid_field", detail)


def validate(record: Mapping[str, Any], headers: Mapping[str, str]) -> StayEvent:
    """A decoded Avro record and its Kafka headers -> a StayEvent, or InvalidEvent saying why not."""
    version = headers.get("schema_version")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise InvalidEvent("schema_version", f"schema_version {version!r} is not supported")
    try:
        event = StayEvent(**{name: record[name] for name in StayEvent.__dataclass_fields__})
    except (KeyError, TypeError) as exc:
        raise InvalidEvent("invalid_field", f"missing or wrong field: {exc}") from exc
    try:
        uuid.UUID(event.event_id)
    except (ValueError, AttributeError, TypeError) as exc:
        raise InvalidEvent("invalid_field", "event_id is not a UUID") from exc
    if headers.get("event_id") not in (None, event.event_id):
        raise InvalidEvent("invalid_field", "event_id header and record disagree")
    _require(event.tenant == TENANT, "unknown tenant")
    _require(event.property in PROPERTIES, "unknown property")
    _require(bool(STAY.fullmatch(event.stay_id)), "stay_id shape")
    _require(event.stay_id.startswith(PROPERTIES.get(event.property, "?") + "-"), "stay_id doesn't match the property")
    _require(bool(MEMBER.fullmatch(event.member_number)), "member_number shape")
    _require(event.nights >= 1 and (event.check_out - event.check_in).days == event.nights, "nights don't match")
    _require(event.room_rate_cents >= 0 and event.taxes_cents >= 0 and event.fees_cents >= 0, "negative money")
    _require(event.currency == "USD", "only USD earns points")
    _require(bool(event.correlation_id), "correlation_id is required")
    if event.revision != 1:
        # Corrections (revision > 1) need RFC-0001 D10's difference rule, which PR-C builds.
        raise InvalidEvent("unsupported_revision", f"revision {event.revision} isn't supported yet")
    return event


def points_for(event: StayEvent) -> int:
    """10 points per US dollar of room rate, rounded down. Taxes, resort fees and pet fees don't earn."""
    return event.room_rate_cents * POINTS_PER_DOLLAR // 100


def ledger_key(event: StayEvent) -> str:
    """The ledger's idempotency key: one credit per stay revision, whatever event ID it arrives under (ADR-0015)."""
    return f"{event.stay_id}:{event.revision}"
