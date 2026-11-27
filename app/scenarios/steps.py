"""What a scenario does, as plain data: the events it sends and the steps of its trigger and its reset.

A plan is built by pure code (`plans.py`) and run by an executor that owns every side effect. So the plans are
unit-tested without a stack, and a dry run can show exactly what a trigger would do.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# How an event is put on the topic.
VALID = "valid"
UNKNOWN_SCHEMA_VERSION = "unknown_schema_version"  # decodable, with a schema_version header nobody supports
UNDECODABLE = "undecodable"  # bytes that are not Avro
EVENT_KINDS = (VALID, UNKNOWN_SCHEMA_VERSION, UNDECODABLE)

# What happened to a member, for the manifest (the ground truth of "affected members").
NOT_POSTED = "not_posted"
DELAYED = "delayed"
CORRECTION_MISSING = "correction_missing"
WRONG_DATES = "wrong_dates"
UNDECIDABLE = "undecidable"
EFFECTS = (NOT_POSTED, DELAYED, CORRECTION_MISSING, WRONG_DATES, UNDECIDABLE)


@dataclass(frozen=True)
class EventSpec:
    """One `stay.checked_out` event to send. `occurred_at` is stamped at send time, plus `clock_offset_seconds`."""

    event_id: str
    member_number: str
    stay_id: str
    revision: int
    nights: int
    room_rate_cents: int
    correlation_id: str
    kind: str = VALID
    copies: int = 1  # more than 1: the same event sent again (a duplicate delivery)
    clock_offset_seconds: int = 0


@dataclass(frozen=True)
class SendEvents:
    events: tuple[EventSpec, ...]
    rate: float  # events a second
    background: bool = False  # keep sending while the next steps run; `JoinSends` waits for it


@dataclass(frozen=True)
class JoinSends:
    pass


@dataclass(frozen=True)
class LedgerControl:
    """The ledger mock's control endpoint. Only these knobs exist; none of them can credit."""

    latency_ms: int | None = None
    rate_per_sec: float | None = None
    burst: int | None = None
    expire_token: bool = False  # set the token's expiry one hour in the past
    clear_token_expiry: bool = False


@dataclass(frozen=True)
class Compose:
    """`docker compose <action>` on stack services. `env` overrides settings the compose file reads."""

    action: str  # stop | start | restart | up
    services: tuple[str, ...]
    env: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class RoleLogin:
    """Let a runtime database role log in, or not (and end its sessions). S07: the posting role only."""

    database: str
    role: str
    allowed: bool


@dataclass(frozen=True)
class RecordChange:
    """A row for the "what changed" feed."""

    service: str
    setting: str
    old: str
    new: str


@dataclass(frozen=True)
class RecordQuestion:
    """A member asking about a stay (S16)."""

    member_number: str
    stay_id: str


@dataclass(frozen=True)
class PlantLog:
    message: str
    correlation_id: str


@dataclass(frozen=True)
class PlantRunbook:
    line: str
    tag: str  # the reset removes the lines with this tag


@dataclass(frozen=True)
class RemoveRunbook:
    tag: str


@dataclass(frozen=True)
class GroupFlap:
    """Extra consumers join and leave a group, `times` times (S14). They never commit an offset."""

    group: str
    times: int
    hold_seconds: float
    gap_seconds: float


@dataclass(frozen=True)
class Wait:
    seconds: float
    reason: str


@dataclass(frozen=True)
class WaitFor:
    """Poll until a condition holds, or fail at the timeout. Conditions (read-only):
    parked_open, outbox_unpublished, lag: compared with `at_least` or `equals`;
    dead_lettered, posted: every event in `event_ids` is in that state."""

    condition: str
    at_least: int | None = None
    equals: int | None = None
    event_ids: tuple[str, ...] = ()
    timeout_seconds: float = 120.0


@dataclass(frozen=True)
class EvaluateAlerts:
    expect_firing: str  # the alert rule that must fire


Step = (
    SendEvents
    | JoinSends
    | LedgerControl
    | Compose
    | RoleLogin
    | RecordChange
    | RecordQuestion
    | PlantLog
    | PlantRunbook
    | RemoveRunbook
    | GroupFlap
    | Wait
    | WaitFor
    | EvaluateAlerts
)
CONDITIONS = ("parked_open", "outbox_unpublished", "lag", "dead_lettered", "posted")


@dataclass(frozen=True)
class Affected:
    member_number: str
    effect: str
    stay_id: str = ""


@dataclass(frozen=True)
class Manifest:
    """The ground truth of one run, from how it was built. Never from a model."""

    scenario: str
    run: int
    pair: str | None
    root_causes: tuple[str, ...]
    recovery: str
    events: tuple[EventSpec, ...]
    affected: tuple[Affected, ...]
    replay_event_ids: tuple[str, ...] = ()  # the exact message set of a correct dlq_replay


@dataclass(frozen=True)
class Plan:
    manifest: Manifest
    trigger: tuple[Step, ...]
    reset: tuple[Step, ...] = field(default=())
