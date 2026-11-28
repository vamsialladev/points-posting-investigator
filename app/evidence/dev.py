"""The 18 dev incidents' evidence snapshots, committed under `benchmarks/snapshots/dev/` (RFC-0002 Phase 3).

One per scenario, at the catalog's default run (0). S15 is pair A, the first of its two fixed pairs. Each file was
taken in GitHub Actions on a new stack, after the scenario's trigger and before its reset, through the read-only
logins (ADR-0022). Before M9 these are the only incidents an arm may be run on (docs/benchmark-protocol.md, 4).

The data is synthetic. A file is evidence as it was read: it is never edited by hand.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.evidence.model import Snapshot
from app.scenarios import catalog

FOLDER = Path(__file__).resolve().parents[2] / "benchmarks" / "snapshots" / "dev"
DEV_RUN = 0
DEV_PAIR = {"S15": "A"}


def name(scenario: str) -> str:
    """The name the scenario tests give this incident's snapshot, e.g. `S05-run0` or `S15-A-run0`."""
    if scenario not in catalog.SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}")
    pair = DEV_PAIR.get(scenario)
    return f"{scenario}{'-' + pair if pair else ''}-run{DEV_RUN}"


def path(scenario: str) -> Path:
    return FOLDER / f"{name(scenario)}.json"


def load(scenario: str) -> Snapshot:
    raw = json.loads(path(scenario).read_text(encoding="utf-8"))
    if raw.get("scenario_run") != name(scenario):
        raise ValueError(f"{path(scenario).name} says it is {raw.get('scenario_run')!r}")
    return Snapshot.from_json(raw)
