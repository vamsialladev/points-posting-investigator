"""The load generator: synthetic checkouts at a set rate, with a hard cap (RFC-0001 PIPE-10). Synthetic data.

    python -m app.pipeline.loadgen --rate 20 --count 200 [--seed 7] [--corrections 0.05] [--duplicates 0.02]

- **Rate:** events a second, paced against a monotonic clock, so a slow send doesn't make the next ones burst.
- **Hard caps:** at most 200 events a second and 10,000 events a run. Larger values are refused, not trimmed.
- **Mix:** each original checkout can be followed later by a correction (revision 2) or sent again unchanged (a
  duplicate, the same event ID), at the given rates. The posting service must credit each stay revision once.
- **Repeatable:** the same seed gives the same events in the same order (seed.py).
- The producer is the checkout producer (ADR-0017): any event Kafka doesn't take raises DeliveryFailed, and the
  generator stops with an error instead of reporting a send that didn't happen.

`plan_load` and `Pacer` are pure (the clock and sleep are passed in), so the caps and the pacing are unit-tested.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.pipeline import seed

MAX_RATE = 200.0
MAX_EVENTS = 10_000


@dataclass(frozen=True)
class LoadSpec:
    count: int  # original checkouts; corrections and duplicates come on top
    rate: float  # events a second, all kinds together
    seed: int = 7
    corrections: float = 0.0  # share of originals followed by a correction
    duplicates: float = 0.0  # share of originals sent twice
    member_count: int = 200
    first_stay: int = 1

    def __post_init__(self) -> None:
        if not 0 < self.rate <= MAX_RATE:
            raise ValueError(f"rate must be above 0 and at most {MAX_RATE:g} events a second")
        if not 0 <= self.corrections <= 1 or not 0 <= self.duplicates <= 1:
            raise ValueError("corrections and duplicates are shares between 0 and 1")
        if self.count < 1 or self.count * (1 + self.corrections + self.duplicates) > MAX_EVENTS:
            raise ValueError(f"a run sends at most {MAX_EVENTS} events, corrections and duplicates included")


@dataclass(frozen=True)
class Planned:
    kind: str  # original | correction | duplicate
    record: dict[str, Any]


def plan_load(spec: LoadSpec) -> list[Planned]:
    """Every event of the run, in send order. A correction or duplicate always comes after its original."""
    rng = random.Random(spec.seed + 1)  # noqa: S311 (synthetic data, not security); +1: apart from the stays' stream
    originals = seed.stays(spec.count, spec.seed, member_count=spec.member_count, first_stay=spec.first_stay)
    plan: list[Planned] = []
    later: list[tuple[int, Planned]] = []  # (send no earlier than this index, event)
    for index, record in enumerate(originals):
        plan.append(Planned("original", record))
        if rng.random() < spec.corrections:
            later.append((index + rng.randint(1, 20), Planned("correction", seed.correction_of(record, rng))))
        if rng.random() < spec.duplicates:
            later.append((index + rng.randint(1, 20), Planned("duplicate", dict(record))))
        due = [item for item in later if item[0] <= index]
        later = [item for item in later if item[0] > index]
        plan.extend(event for _, event in due)
    plan.extend(event for _, event in later)
    if len(plan) > MAX_EVENTS:  # a guard on the guard: LoadSpec already refuses this
        raise ValueError(f"planned {len(plan)} events, more than {MAX_EVENTS}")
    return plan


class Pacer:
    """Waits so that event n goes out no earlier than start + n / rate. It never bursts to catch up beyond that."""

    def __init__(self, rate: float, clock: Callable[[], float], sleep: Callable[[float], None]) -> None:
        self.interval, self.clock, self.sleep = 1.0 / rate, clock, sleep
        self.start: float | None = None
        self.sent = 0

    def wait(self) -> float:
        """Sleep until the next event is due; returns how long it slept."""
        now = self.clock()
        if self.start is None:
            self.start = now
        due = self.start + self.sent * self.interval
        self.sent += 1
        if due > now:
            self.sleep(due - now)
            return due - now
        return 0.0


@dataclass(frozen=True)
class LoadResult:
    sent: int
    originals: int
    corrections: int
    duplicates: int
    seconds: float


def run(plan: list[Planned], producer: Any, pacer: Pacer, clock: Callable[[], float] = time.monotonic) -> LoadResult:
    """Send the plan, paced. Each send waits for Kafka's answer (DeliveryFailed stops the run)."""
    started = clock()
    for event in plan:
        pacer.wait()
        producer.send(event.record)
    kinds = [event.kind for event in plan]
    return LoadResult(
        len(plan), kinds.count("original"), kinds.count("correction"), kinds.count("duplicate"), clock() - started
    )


def main(argv: list[str] | None = None) -> int:
    from confluent_kafka.schema_registry import SchemaRegistryClient
    from dotenv import load_dotenv

    from app.pipeline.producer import CheckoutProducer, make_checkout_producer

    load_dotenv(override=False)
    parser = argparse.ArgumentParser(description="Send synthetic stay.checked_out events at a set rate (capped)")
    parser.add_argument("--count", type=int, required=True, help="original checkouts")
    parser.add_argument("--rate", type=float, required=True, help=f"events a second (max {MAX_RATE:g})")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--corrections", type=float, default=0.0)
    parser.add_argument("--duplicates", type=float, default=0.0)
    parser.add_argument("--first-stay", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        spec = LoadSpec(args.count, args.rate, args.seed, args.corrections, args.duplicates, first_stay=args.first_stay)
        plan = plan_load(spec)
    except ValueError as exc:
        raise SystemExit(f"refused: {exc}") from exc
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092").replace("localhost", "127.0.0.1")
    registry = SchemaRegistryClient({"url": os.environ.get("SCHEMA_REGISTRY_URL", "http://127.0.0.1:8081")})
    producer = CheckoutProducer(make_checkout_producer(bootstrap), registry)
    result = run(plan, producer, Pacer(spec.rate, time.monotonic, time.sleep))
    print(
        f"sent {result.sent} synthetic events ({result.originals} originals, {result.corrections} corrections,"
        f" {result.duplicates} duplicates) in {result.seconds:.1f} s to {producer.topic}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
