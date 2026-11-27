# Backlog

New ideas go here, not into the build (spec 0.5). Nothing here is built until the owner approves it. v2 items from the
spec are not ideas: they are in `docs/implementation-plan.md` §2 and in the requirements matrix.

## Ideas awaiting the owner's decision
| Idea | Why it might matter | Source | Status |
|---|---|---|---|
| A Java / Spring Boot posting service | Shows the owner's Java and distributed-systems background in code | spec 0.4 (out of scope), ADR-0005 | Not approved |
| Extract shared patterns (preflight, leak scanner, REQUIRE_MARKERS guard, approval binding) into `hotel-ai-platform` | Stages 9 and 10 now hold copies; a third copy is the trigger | ADR-0003 | Not approved |
| Consume Stage 9's own OpenTelemetry traces as a second telemetry source | Stage 9's backlog says it "emits OpenTelemetry traces Stage 10 could consume" | Stage 9 `docs/backlog.md` | Not approved |
| A durable-workflow engine (for example Temporal) for the automation engine | The comparison in `docs/automation-decision.md` (v2) may favour it at scale | spec F2 | Not approved |
| The ledger `members` table and member validation (RFC-0001 change 6), moved from M2 PR-C to M3 | Nothing in M2 reads it; an "unknown member" failure scenario in M3 would | ADR-0018 | Deferred to M3 (owner confirmed 2026-11-27) |
