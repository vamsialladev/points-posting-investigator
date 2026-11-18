# AI Points-Posting Incident Investigator

> **Stage 10 of a simulated client engagement** for a fictional hotel group (Beach Resort, Mountain Lodge). All the
> data is synthetic, and every person in the documents is simulated. Independent portfolio project.
> Stage 9: [loyalty-support-modernization](https://github.com/vamsialladev/loyalty-support-modernization).
> Discovery and scoping (stage 0): [hotel-ai-discovery](https://github.com/vamsialladev/hotel-ai-discovery).

Stage 9 found that some "missing points" cases come from failures in the hotel group's points-posting pipeline:
checkout events → posting service → loyalty ledger. This project builds that pipeline and the failures, then:
- an alert-triggered AI investigator that only reads telemetry and cites it
- human-approved recovery that cannot double-post points
- a fair benchmark against manual and rules-only investigation

## What exists today (Milestone 2 in progress)
This repository holds the specification, the plan, the working setup and the first part of the pipeline:
- a local Docker stack (Kafka, a schema registry, Postgres)
- the loyalty-ledger mock, which refuses to credit one event twice at the database level
- CI that runs the tests on real Kafka and Postgres

There's no posting service, investigator or benchmark yet. Everything is local and synthetic.

| Part | Where |
|---|---|
| Specification | [docs/MASTER-SPEC.md](docs/MASTER-SPEC.md) |
| Release plan (v1, then v2) | [docs/implementation-plan.md](docs/implementation-plan.md) |
| Fictional discovery and workflow | [docs/discovery.md](docs/discovery.md), [docs/workflow.md](docs/workflow.md) |
| How it fits stages 0–9 | [docs/continuity.md](docs/continuity.md) |
| Status of every requirement | [docs/requirements-matrix.md](docs/requirements-matrix.md) |
| Decisions | [docs/decisions.md](docs/decisions.md) |
| Configuration check that never prints a value | `app/preflight.py` |

## Run the checks (Windows, PowerShell)
```powershell
uv sync
powershell -ExecutionPolicy Bypass -File scripts\test.ps1
powershell -ExecutionPolicy Bypass -File scripts\new_env.ps1           # creates .env, prints no values
powershell -ExecutionPolicy Bypass -File scripts\preflight.ps1 -Profile core
powershell -ExecutionPolicy Bypass -File scripts\stack.ps1 up             # Docker: Kafka, registry, Postgres, ledger
powershell -ExecutionPolicy Bypass -File scripts\test_integration.ps1     # tests on the real stack
```

An `.env` made before Milestone 2 needs two new local values: `scripts\new_env.ps1 -AddMissing` adds them and keeps
everything else.

macOS / Linux: `uv sync`, `make test`, `make preflight PROFILE=core`.

## License
MIT. See [LICENSE](LICENSE).
