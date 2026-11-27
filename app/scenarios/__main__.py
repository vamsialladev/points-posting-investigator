"""Show a scenario's plan. Read-only: this command touches nothing.

    python -m app.scenarios list
    python -m app.scenarios plan S05 [--run 3] [--pair A]

`trigger` and `reset` arrive with the executor (RFC-0002 Phase 2); until then this shows what they will do.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from typing import Any

from app.scenarios import catalog
from app.scenarios.plans import MAX_RUN, plan
from app.scenarios.steps import Plan, Step


def step_json(step: Step) -> dict[str, Any]:
    return {"step": type(step).__name__, **dataclasses.asdict(step)}


def plan_json(built: Plan) -> dict[str, Any]:
    return {
        "manifest": dataclasses.asdict(built.manifest),
        "trigger": [step_json(step) for step in built.trigger],
        "reset": [step_json(step) for step in built.reset],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The 18 pre-registered failure scenarios (simulated, synthetic data)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="the scenarios and their ground truth")
    show = commands.add_parser("plan", help="what a trigger and its reset would do, as JSON")
    show.add_argument("scenario", choices=sorted(catalog.SCENARIOS))
    show.add_argument("--run", type=int, default=0, help=f"0..{MAX_RUN}; each run has its own members and stays")
    show.add_argument("--pair", choices=catalog.PAIRS, help="S15 only")
    args = parser.parse_args(argv)

    if args.command == "list":
        for scenario in catalog.SCENARIOS.values():
            if scenario.id == "S15":
                truth = "; ".join(f"pair {k}: {' + '.join(p.root_causes)}" for k, p in catalog.S15_PAIRS.items())
            else:
                truth = f"{scenario.root_causes[0]}; recovery {scenario.recovery}"
            print(f"{scenario.id}  {scenario.name}: {truth}")
        return 0
    try:
        built = plan(args.scenario, args.run, args.pair)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(plan_json(built), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
