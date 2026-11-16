# Onboarding (for a newly joined engineer)

Updated at the end of every milestone. **Current: Milestone 1 (2026-11-16).** Independent portfolio simulation:
fictional hotel group, synthetic data, simulated people.

## 1. What this system does (when built)
A synthetic hotel group's checkout events flow through Kafka to a posting service, which credits a loyalty ledger.
The repo then:
- injects failures from a pre-registered catalog
- fires alerts
- runs an AI investigator that only reads telemetry and cites it
- lets a person approve a bounded recovery that can't double-post points

A benchmark compares three ways of investigating: a manual runbook, rules only, and AI-assisted. Today (M1) only the
setup exists.

## 2. Run it (Windows, PowerShell, from this folder)
```powershell
uv sync
powershell -ExecutionPolicy Bypass -File scripts\test.ps1                       # lint, format, types, tests
powershell -ExecutionPolicy Bypass -File scripts\new_env.ps1                    # creates .env; prints no values
powershell -ExecutionPolicy Bypass -File scripts\preflight.ps1 -Profile core    # set / missing per name
powershell -ExecutionPolicy Bypass -File scripts\ci_local.ps1                   # the CI pipeline locally
```

## 3. Where things live
| Path | What |
|---|---|
| `docs/MASTER-SPEC.md` | The specification (source of truth) |
| `CLAUDE.md`, `AGENTS.md` | Rules for coding assistants (the owner's ten standing rules) |
| `docs/implementation-plan.md` | v1 and v2 |
| `docs/requirements-matrix.md` | Every requirement, its release, milestone and status |
| `app/preflight.py` | Settings readiness per profile; never prints a value |
| `app/env_leaks.py` | Looks for `.env` values in tracked files |
| `tests/required_markers.py` | Makes skipped infrastructure tests fail where they must run |
| `scripts/` | PowerShell twins of every make target |

## 4. Why the key decisions were made
- **ADR-0001:** Claude Code builds; Codex is optional.
- **ADR-0002:** v1 first; pre-registration moved before any arm code.
- **ADR-0003:** port Stage 9's patterns.
- **ADR-0006:** preflight profiles.
- **ADR-0007:** checks that check nothing fail.

## 5. Common failure modes so far
- **A `${NAME}` reference in `.env` above the line that defines it** expands to a blank string. Preflight names the
  line (Stage 9's first-run bug).
- **A green test run that skipped everything.** Set `REQUIRE_MARKERS` where the services must be up.
- **A false "leak" in a test** because a fake value was a common word ("points" appears in report text). Use
  distinctive fake values.
- **pytest's `-m` deselection runs after `pytest_collection_modifyitems` hooks see the items.** Count selected tests
  at `pytest_collection_finish`.

## 6. Starter-kit candidates vs customer-specific
- **Generalises:**
  - the preflight pattern (variables registry, profiles, never print a value)
  - the NOT RUN leak scanner
  - the `REQUIRE_MARKERS` guard
  - the tracking-file set
- **Customer-specific:** variable names, profiles, and the hotel-group storyline.

## 7. First tasks to try
1. Run `scripts\test.ps1`, then break one preflight check and see which test fails.
2. Run `scripts\leaks.ps1` before and after creating `.env`. Explain why the first run fails (ADR-0007).
3. Read `docs/discovery.md` §9 and argue for moving one row between the two columns.
