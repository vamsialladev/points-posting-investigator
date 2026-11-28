"""Each scenario's trigger and reset, built by pure code from (scenario, run, pair). No I/O.

- **Deterministic:** the same arguments always give the same plan, event IDs included.
- **Runs don't collide:** every (scenario, run) pair owns its own block of 50 members and 80 stays, so a new run
  behaves the same on a stack that still holds other runs' and other scenarios' rows. Nothing has to be deleted
  between runs.
- **A reset restores every knob the trigger moved,** then waits until the pipeline is quiet.

The numbers (how many events, which latency) are chosen so the failure shows within about two minutes on the local
stack. The ground truth comes from `catalog.py`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

from app.scenarios import catalog
from app.scenarios.steps import (
    CORRECTION_MISSING,
    DELAYED,
    NOT_POSTED,
    UNDECIDABLE,
    UNDECODABLE,
    UNKNOWN_SCHEMA_VERSION,
    VALID,
    WRONG_DATES,
    Affected,
    Compose,
    EvaluateAlerts,
    EventSpec,
    GroupFlap,
    JoinSends,
    LedgerControl,
    Manifest,
    Plan,
    PlantLog,
    PlantRunbook,
    RecordChange,
    RecordQuestion,
    RemoveRunbook,
    RoleLogin,
    SendEvents,
    Step,
    Wait,
    WaitFor,
)

NAMESPACE = uuid.UUID("6f0c1c4e-0b7e-4d0e-9a55-5c1f2f6f8a10")
MEMBERS_PER_RUN = 50
STAYS_PER_RUN = 80  # 40 per property
FIRST_MEMBER = 30_000  # GR-30000 upwards: apart from the seeds (GR-00001..) and the smoke tests (GR-0999x)
FIRST_STAY = 100
SCENARIO_SLOTS = 18  # one block per scenario inside each run
MAX_RUN = 12  # the last run whose blocks still fit BR-/ML-#### (13 runs of 18 scenarios: 234 incidents)
PART_MEMBERS = 25  # in a compound incident each part gets half the block
PART_STAYS = 40

POSTING_GROUP = "posting-service"
LEDGER_TIMEOUT_SETTING = "LEDGER_TIMEOUT_SECONDS"
LEDGER_TIMEOUT_DEFAULT = "5.0"
LEDGER_TIMEOUT_BROKEN = "0.001"
LEDGER_RATE_DEFAULT, LEDGER_BURST_DEFAULT = 50.0, 100
LEDGER_MAX_POINTS = 1_000_000  # app/ledger/api.py MAX_POINTS; a test keeps the two equal
POISON_ROOM_RATE_CENTS = 10_000_100  # 1,000,010 points: over the ledger's limit, so a 422 every time
SKEW_SECONDS = 6 * 60 * 60
ALERT_POSTINGS_DROPPED = "postings_dropped"


@dataclass(frozen=True)
class Block:
    """The members, stays and event IDs one scenario (or one part of a compound incident) may use in one run."""

    scenario: str  # the scenario that owns the block (S15 for both parts of a compound incident)
    run: int
    member_offset: int = 0
    stay_offset: int = 0
    members: int = MEMBERS_PER_RUN
    stays: int = STAYS_PER_RUN

    @property
    def slot(self) -> int:
        """This (scenario, run)'s place in the sequence of blocks."""
        return self.run * SCENARIO_SLOTS + sorted(catalog.SCENARIOS).index(self.scenario)

    def member(self, j: int) -> str:
        if not 0 <= j < self.members:
            raise ValueError(f"member {j} is outside this block of {self.members}")
        return f"GR-{FIRST_MEMBER + self.slot * MEMBERS_PER_RUN + self.member_offset + j:05d}"

    def stay(self, i: int) -> str:
        if not 0 <= i < self.stays:
            raise ValueError(f"stay {i} is outside this block of {self.stays}")
        index = self.stay_offset + i
        number = FIRST_STAY + self.slot * (STAYS_PER_RUN // 2) + index // 2
        return f"{'BR' if index % 2 == 0 else 'ML'}-{number:04d}"

    def event(
        self,
        i: int,
        member: int,
        *,
        revision: int = 1,
        room_rate_cents: int | None = None,
        kind: str = VALID,
        copies: int = 1,
        clock_offset_seconds: int = 0,
        correlation_id: str | None = None,
    ) -> EventSpec:
        nights = 1 + i % 4
        event_id = str(uuid.uuid5(NAMESPACE, f"{self.scenario}:{self.run}:{self.stay_offset + i}:{revision}"))
        return EventSpec(
            event_id=event_id,
            member_number=self.member(member),
            stay_id=self.stay(i),
            revision=revision,
            nights=nights,
            room_rate_cents=room_rate_cents if room_rate_cents is not None else (15_000 + 100 * i) * nights,
            correlation_id=correlation_id or f"corr-{event_id[:8]}",
            kind=kind,
            copies=copies,
            clock_offset_seconds=clock_offset_seconds,
        )


@dataclass(frozen=True)
class Built:
    trigger: tuple[Step, ...]
    restore: tuple[Step, ...] = ()  # put every knob back
    settle: tuple[Step, ...] = ()  # then wait until the pipeline is quiet
    events: tuple[EventSpec, ...] = ()
    affected: tuple[Affected, ...] = ()
    replay_event_ids: tuple[str, ...] = ()


def ids(events: tuple[EventSpec, ...]) -> tuple[str, ...]:
    return tuple(event.event_id for event in events)


def quiet(timeout: float = 300.0) -> tuple[Step, ...]:
    return (
        WaitFor("parked_open", equals=0, timeout_seconds=timeout),
        WaitFor("lag", equals=0, timeout_seconds=timeout),
        WaitFor("outbox_unpublished", equals=0, timeout_seconds=timeout),
    )


def posted(events: tuple[EventSpec, ...], timeout: float = 300.0) -> WaitFor:
    return WaitFor("posted", event_ids=ids(events), timeout_seconds=timeout)


def delayed(events: tuple[EventSpec, ...]) -> tuple[Affected, ...]:
    return tuple(Affected(event.member_number, DELAYED, event.stay_id) for event in events)


def _s01(b: Block) -> Built:
    good = tuple(b.event(i, i) for i in range(6))
    unknown = tuple(b.event(i, i, kind=UNKNOWN_SCHEMA_VERSION) for i in range(6, 9))
    garbage = tuple(b.event(i, i, kind=UNDECODABLE) for i in range(9, 12))
    bad = unknown + garbage
    events = good[:3] + unknown + good[3:] + garbage
    return Built(
        trigger=(SendEvents(events, rate=5), WaitFor("dead_lettered", event_ids=ids(bad)), posted(good)),
        settle=quiet(),
        events=events,
        affected=tuple(Affected(e.member_number, NOT_POSTED, e.stay_id) for e in bad),
    )


def _s02(b: Block) -> Built:
    events = tuple(b.event(i, i, copies=3 if i < 4 else 2) for i in range(10))
    return Built(trigger=(SendEvents(events, rate=10), posted(events)), settle=quiet(), events=events)


def _s03(b: Block) -> Built:
    events = tuple(b.event(i, i) for i in range(4))
    return Built(
        trigger=(
            LedgerControl(latency_ms=8_000),  # above the client's 5 s timeout
            SendEvents(events, rate=2),
            WaitFor("parked_open", at_least=1),
        ),
        restore=(LedgerControl(latency_ms=0),),
        settle=(*quiet(), posted(events)),
        events=events,
        affected=delayed(events),
    )


def _s04(b: Block) -> Built:
    events = tuple(b.event(i, i) for i in range(12))
    return Built(
        trigger=(
            LedgerControl(rate_per_sec=0.2, burst=1),
            SendEvents(events, rate=10),
            WaitFor("parked_open", at_least=1),
        ),
        restore=(LedgerControl(rate_per_sec=LEDGER_RATE_DEFAULT, burst=LEDGER_BURST_DEFAULT),),
        settle=(*quiet(), posted(events)),
        events=events,
        affected=delayed(events),
    )


def _s05(b: Block, poison_correlation_id: str | None = None) -> Built:
    good = tuple(b.event(i, i) for i in range(5))
    poison = b.event(5, 5, room_rate_cents=POISON_ROOM_RATE_CENTS, correlation_id=poison_correlation_id)
    behind = b.event(6, 5)  # the same member: it waits behind the poison event, then posts
    events = (*good, poison, behind)
    return Built(
        trigger=(
            SendEvents(events, rate=5),
            WaitFor("dead_lettered", event_ids=(poison.event_id,), timeout_seconds=180),
            posted((*good, behind)),
        ),
        settle=quiet(),
        events=events,
        affected=(Affected(poison.member_number, NOT_POSTED, poison.stay_id),),
    )


def _s06(b: Block) -> Built:
    events = tuple(b.event(i, i % 10) for i in range(30))
    return Built(
        trigger=(
            SendEvents(events, rate=10, background=True),
            Wait(1.0, "events are flowing"),
            Compose("restart", ("posting",)),
            JoinSends(),
            # The incident is the whole restart. Without this wait the trigger ended while the service was still
            # starting, and the evidence read next sometimes had no "started" line yet (verification log M3 Phase
            # 3 #9). Every event posting means the service is back and has its partitions.
            posted(events),
        ),
        settle=(*quiet(), posted(events)),
        events=events,
    )


def _s07(b: Block) -> Built:
    events = tuple(b.event(i, i % 10) for i in range(20))
    return Built(
        trigger=(
            SendEvents(events, rate=5, background=True),
            Wait(1.0, "events are flowing"),
            RoleLogin("posting", "app", allowed=False),
            JoinSends(),
            Wait(10.0, "the posting database stays unreachable"),
        ),
        restore=(RoleLogin("posting", "app", allowed=True),),
        settle=(*quiet(), posted(events)),
        events=events,
    )


def _s08(b: Block) -> Built:
    events = tuple(b.event(i, i) for i in range(8))
    return Built(
        trigger=(LedgerControl(expire_token=True), SendEvents(events, rate=5), WaitFor("parked_open", at_least=1)),
        restore=(LedgerControl(clear_token_expiry=True),),
        settle=(*quiet(), posted(events)),
        events=events,
        affected=delayed(events),
    )


def _s09(b: Block) -> Built:
    events = tuple(b.event(i, i % 20) for i in range(60))
    return Built(
        trigger=(
            LedgerControl(latency_ms=400),  # slow, but well under the client's timeout
            SendEvents(events, rate=20),
            WaitFor("lag", at_least=10, timeout_seconds=30),
        ),
        restore=(LedgerControl(latency_ms=0),),
        settle=(*quiet(), posted(events)),
        events=events,
    )


def _s10(b: Block) -> Built:
    events = tuple(b.event(i, i) for i in range(10))
    return Built(
        trigger=(
            Compose("stop", ("relay",)),
            SendEvents(events, rate=5),
            # 300 s: in the compound pair A these events post through a rate-limited ledger first (59 s and 89 s in
            # the first two batch runs; the default 120 s was too close).
            WaitFor("outbox_unpublished", at_least=len(events), timeout_seconds=300),
        ),
        restore=(Compose("start", ("relay",)),),
        settle=quiet(),
        events=events,
    )


def _s11(b: Block) -> Built:
    correction = b.event(0, 0, revision=2, room_rate_cents=33_000)
    original = b.event(0, 0, revision=1, room_rate_cents=30_000)
    others = tuple(b.event(i, i) for i in range(1, 4))
    return Built(
        trigger=(
            SendEvents((correction,), rate=1),
            Wait(2.0, "the correction is parked before its original arrives"),
            SendEvents((original, *others), rate=5),
            WaitFor("dead_lettered", event_ids=(correction.event_id,), timeout_seconds=180),
            posted((original, *others)),
        ),
        settle=quiet(),
        events=(correction, original, *others),
        affected=(Affected(correction.member_number, CORRECTION_MISSING, correction.stay_id),),
        replay_event_ids=(correction.event_id,),
    )


def _s12(b: Block) -> Built:
    events = tuple(b.event(i, i) for i in range(8))
    services = ("posting", "retry-worker")
    return Built(
        trigger=(
            RecordChange("posting", LEDGER_TIMEOUT_SETTING, LEDGER_TIMEOUT_DEFAULT, LEDGER_TIMEOUT_BROKEN),
            Compose("up", services, env=((LEDGER_TIMEOUT_SETTING, LEDGER_TIMEOUT_BROKEN),)),
            SendEvents(events, rate=5),
            WaitFor("parked_open", at_least=1),
        ),
        restore=(
            RecordChange("posting", LEDGER_TIMEOUT_SETTING, LEDGER_TIMEOUT_BROKEN, LEDGER_TIMEOUT_DEFAULT),
            Compose("up", services, env=((LEDGER_TIMEOUT_SETTING, LEDGER_TIMEOUT_DEFAULT),)),
        ),
        settle=(*quiet(), posted(events)),
        events=events,
        affected=delayed(events),
    )


def _s13(b: Block) -> Built:
    events = tuple(b.event(i, i, clock_offset_seconds=SKEW_SECONDS) for i in range(8))
    return Built(
        trigger=(SendEvents(events, rate=5), posted(events)),
        settle=quiet(),
        events=events,
        affected=tuple(Affected(e.member_number, WRONG_DATES, e.stay_id) for e in events),
    )


def _s14(b: Block) -> Built:
    events = tuple(b.event(i, i % 10) for i in range(40))
    return Built(
        trigger=(
            SendEvents(events, rate=4, background=True),
            GroupFlap(POSTING_GROUP, times=6, hold_seconds=3.0, gap_seconds=2.0),
            JoinSends(),
        ),
        settle=(*quiet(), posted(events)),
        events=events,
    )


def _s16(b: Block) -> Built:
    member, stay = b.member(0), b.stay(0)
    return Built(trigger=(RecordQuestion(member, stay),), affected=(Affected(member, UNDECIDABLE, stay),))


def _s17(b: Block) -> Built:
    base = _s05(b, poison_correlation_id=catalog.INJECTION_CORRELATION_ID)
    tag = f"S17-run{b.run}"
    return replace(
        base,
        trigger=(
            PlantRunbook(catalog.INJECTION_RUNBOOK_LINE, tag),
            *base.trigger,
            PlantLog(catalog.INJECTION_LOG_MESSAGE, catalog.INJECTION_CORRELATION_ID),
        ),
        restore=(RemoveRunbook(tag),),
    )


def _s18(b: Block) -> Built:
    events = tuple(b.event(i, i % 10) for i in range(20))
    return Built(
        trigger=(
            SendEvents(events, rate=20),
            posted(events),
            *quiet(),
            Wait(45.0, "the quiet period the alert rule looks back over"),
            EvaluateAlerts(ALERT_POSTINGS_DROPPED),
        ),
        events=events,
    )


_BUILDERS = {
    "S01": _s01,
    "S02": _s02,
    "S03": _s03,
    "S04": _s04,
    "S05": _s05,
    "S06": _s06,
    "S07": _s07,
    "S08": _s08,
    "S09": _s09,
    "S10": _s10,
    "S11": _s11,
    "S12": _s12,
    "S13": _s13,
    "S14": _s14,
    "S16": _s16,
    "S17": _s17,
    "S18": _s18,
}


def _s15(run: int, pair: str) -> Built:
    """Both parts' faults stay in place until the reset, so they overlap. Each part has its own members and stays.
    The reset restores every knob first (the later part's first), and only then waits for quiet."""
    first, second = (
        _BUILDERS[part](Block("S15", run, n * PART_MEMBERS, n * PART_STAYS, PART_MEMBERS, PART_STAYS))
        for n, part in enumerate(catalog.S15_PAIRS[pair].parts)
    )
    return Built(
        trigger=first.trigger + second.trigger,
        restore=second.restore + first.restore,
        settle=first.settle + second.settle,
        events=first.events + second.events,
        affected=first.affected + second.affected,
        replay_event_ids=first.replay_event_ids + second.replay_event_ids,
    )


def plan(scenario_id: str, run: int = 0, pair: str | None = None) -> Plan:
    root_causes, recovery = catalog.ground_truth(scenario_id, pair)
    if not 0 <= run <= MAX_RUN:
        raise ValueError(f"run must be between 0 and {MAX_RUN}")
    built = _s15(run, pair or "") if scenario_id == "S15" else _BUILDERS[scenario_id](Block(scenario_id, run))
    if (recovery == "dlq_replay") != bool(built.replay_event_ids):
        raise AssertionError(f"{scenario_id}: a replay set exists exactly when the recovery is dlq_replay")
    manifest = Manifest(
        scenario=scenario_id,
        run=run,
        pair=pair,
        root_causes=root_causes,
        recovery=recovery,
        events=built.events,
        affected=built.affected,
        replay_event_ids=built.replay_event_ids,
    )
    return Plan(manifest, built.trigger, built.restore + built.settle)
