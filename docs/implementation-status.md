# Implementation status

- **Last updated:** 2026-11-16
- **Current milestone:** 1 (complete)
- **Next:** Milestone 2 (design-heavy: RFC-0001 plan first, then the owner's approval)
- **Waiting on the owner:** see `docs/session-handoff.md`

## Milestones
| M | Name | Release | Status |
|---|---|---|---|
| 1 | Workspace, continuity, tracking, preflight, discovery | v1 | Implemented and verified |
| 2 | Kafka, schema registry, Postgres, pipeline, outbox, idempotent ledger | v1 | Planned (M2) |
| 3 | Pre-registration (catalog, hypotheses, thresholds, protocol), scenario triggers and resets | v1 | Planned (M3) |
| 4 | Observability, dashboards, alert rules, change feed, runbooks | v1 | Planned (M4) |
| 5 | Arms A and B | v1 | Planned (M5) |
| 6 | AI investigator (arm C) on the mock provider | v1 | Planned (M6) |
| 7 | Recovery controls | v1 | Planned (M7) |
| 8 | UI, auth, minimal automation slice, Playwright end to end | v1 | Planned (M8) |
| 9 | Benchmark | v1 | Planned (M9) |
| 10 | Automation engine in full + n8n | v2 | Planned (v2) |
| 11 | Stage 9 adapter + MCP read-only tools | v2 | Planned (v2) |
| 12 | Security hardening + threat model (v1 slice: draft, SECURITY.md) | v1 slice / v2 | Planned (M8) |
| 13 | CI, IaC, cloud (v1 slice: CI only) | v1 slice / v2 | Planned (M2) |
| 14 | Game days + post-incident review | v2 | Planned (v2) |
| 15 | Handover and UAT docs | v2 | Planned (v2) |
| 16 | Portfolio package (v1 slice: README, video, case study, card) | v1 slice / v2 | Planned (M16) |
| 17 | Clean-install verification | v1 / v2 | Planned (M17) |

## Status vocabulary (spec 0.3)
These are the only statuses used in `docs/requirements-matrix.md`:
- Implemented and verified
- Implemented but unverified
- Simulated
- Documentation-only
- Manual step required
- Blocked (prerequisite)
- Deferred (reason)

Plus `Planned (M#)` for a v1 requirement no milestone has reached, and `Planned (v2)` for "what's next".

## Counts (from `docs/requirements-matrix.md`, 2026-11-16)
`tests/test_repo_guidance.py::test_status_counts_match_the_matrix` keeps this table honest.

| Release | Rows | Implemented and verified | Manual step required | Planned |
|---|---|---|---|---|
| v1 | 142 | 34 | 0 | 108 |
| v2 | 32 | 0 | 0 | 32 |
