"""The 18 pre-registered failure scenarios, on the LOCAL stack only (simulated system, synthetic data).

    python -m app.scenarios list
    python -m app.scenarios plan S05 [--run 3] [--pair A]      # read-only: shows what would happen
    python -m app.scenarios trigger S05 [--run 3]              # breaks the local stack on purpose
    python -m app.scenarios reset S05 [--run 3]                # restores every knob, waits until quiet

`trigger` and `reset` refuse any address that isn't this machine, and refuse PUBLIC_DEMO_MODE=true. Each run has its
own members and stays, so nothing is deleted between runs. Exit code 0 = every step succeeded, 1 = a step failed.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable

from app.scenarios import catalog, run
from app.scenarios.executor import Effects
from app.scenarios.plans import MAX_RUN, plan
from app.scenarios.run import plan_json

__all__ = ["main", "plan_json"]


def main(argv: list[str] | None = None, effects: Callable[[], Effects] = run.stack_effects) -> int:
    parser = argparse.ArgumentParser(description="The 18 pre-registered failure scenarios (simulated, synthetic data)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="the scenarios and their ground truth")
    helps = {
        "plan": "what a trigger and its reset would do, as JSON (read-only)",
        "trigger": "break the local stack as the scenario says",
        "reset": "restore every knob the trigger moved, then wait until the pipeline is quiet",
    }
    for name, text in helps.items():
        sub = commands.add_parser(name, help=text)
        sub.add_argument("scenario", choices=sorted(catalog.SCENARIOS))
        sub.add_argument("--run", type=int, default=0, help=f"0..{MAX_RUN}; each run has its own members and stays")
        sub.add_argument("--pair", choices=catalog.PAIRS, help="S15 only")
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
    if args.command == "plan":
        print(json.dumps(plan_json(built), indent=2))
        return 0
    try:
        stack = effects()
    except Exception as exc:  # NotLocal, a missing setting, an unreachable stack: say which, never a value
        print(f"refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return 0 if run.execute(args.command, args.scenario, args.run, args.pair, stack) else 1


if __name__ == "__main__":
    sys.exit(main())
