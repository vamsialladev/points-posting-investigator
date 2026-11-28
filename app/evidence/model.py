"""One piece of evidence, and a snapshot of many. Plain data, JSON-ready. No I/O."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

KINDS = (
    "posting",
    "outbox",
    "parked",
    "skipped",
    "credit",
    "event",
    "dead_letter",
    "lag",
    "log",
    "change",
    "question",
    "alert",
)
# Fields whose text was written by another system or a person. Data, never instructions.
UNTRUSTED = frozenset(
    {"message", "last_error", "error_detail", "correlation_id", "question", "body", "old_value", "new_value"}
)
TEXT_LIMIT = 300


def clip(value: Any) -> Any:
    """Bound a text value. Other values pass through."""
    if isinstance(value, str) and len(value) > TEXT_LIMIT:
        return value[:TEXT_LIMIT] + "…"
    return value


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass(frozen=True)
class Evidence:
    id: str  # the citation: "<kind>:<where>", stable for the same row, offset or snapshot
    kind: str
    at: str | None  # when it happened or was stored (ISO 8601), if the source says
    data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown evidence kind {self.kind!r}")
        if not self.id.startswith(f"{self.kind}:"):
            raise ValueError(f"an evidence id starts with its kind: {self.id!r}")


def evidence(kind: str, where: str, at: datetime | None, **data: Any) -> Evidence:
    return Evidence(f"{kind}:{where}", kind, iso(at), {name: clip(value) for name, value in data.items()})


@dataclass(frozen=True)
class Snapshot:
    """Everything read for one question, at one moment. `items` is in a fixed order, so two snapshots compare."""

    taken_at: str
    since: str
    items: tuple[Evidence, ...]
    truncated: tuple[str, ...] = ()  # the kinds whose read hit its limit: there may be more than is shown

    def of(self, kind: str) -> list[Evidence]:
        return [item for item in self.items if item.kind == kind]

    def ids(self) -> set[str]:
        return {item.id for item in self.items}

    def to_json(self) -> dict[str, Any]:
        return {
            "taken_at": self.taken_at,
            "since": self.since,
            "truncated": list(self.truncated),
            "items": [asdict(item) | {"data": dict(item.data)} for item in self.items],
        }

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> Snapshot:
        items = tuple(Evidence(i["id"], i["kind"], i["at"], dict(i["data"])) for i in document["items"])
        return cls(document["taken_at"], document["since"], items, tuple(document.get("truncated", ())))
