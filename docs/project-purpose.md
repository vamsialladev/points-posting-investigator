# Project purpose

Stage 10 adopts Stage 9's purpose and its 11 lenses unchanged (standing rule 8). The owner's words are kept verbatim
in `loyalty-support-modernization/docs/project-purpose.md` (set 2026-10-28). This file says how Stage 10 applies them
and does not restate them.

## 1. What Stage 10 adds to the purpose
Stage 9 is the reusable, end-to-end FDE engagement for a support workflow. Stage 10 adds the parts a customer's
platform and SRE teams own:
- an event-driven integration
- observability
- incident response
- an AI that acts automatically **but only reads and recommends**

The lens most specific to Stage 10 is **Operations**: alerts, runbooks, recovery, drills.

## 2. The lenses, applied proportionately
The 11 lenses: business, data, AI, engineering, security and governance, operations, people, tools, reuse,
principal engineering, every role. They are applied inside each milestone's existing work, never as extra scope.

| Artifact | Starts | Updated |
|---|---|---|
| ADRs with options considered and what would change the decision (`docs/decisions.md`) | M1 | with every important decision |
| `docs/onboarding.md` | M1 | end of every milestone |
| `docs/role-coverage-map.md` | M1 | end of every milestone, with evidence only |
| `docs/real-system-swap-guide.md` | M2 (first mock: the ledger) | each milestone that adds or changes a mock or adapter |
| `docs/technical-strategy.md`, `docs/scaling-and-limits.md`, `docs/tech-debt-register.md`, `docs/tco.md` | M2 | end of every milestone, short, estimates labelled |
| `docs/fde-tool-map.md`, `docs/tool-access-matrix.md` | M2 (Kafka, schema registry) | whenever a tool's role, access or status changes |
| `docs/rfcs/` | M2 | one per design-heavy milestone: 2, 3, 6, 7, 9, 10 |
| `docs/executive-brief.md` | end of M3 (pre-registration phase) | end of each phase: build (M3), evidence (M9), release (M17) |

"Proportionate" means a short entry when a milestone touched a lens lightly, and no entry when it didn't touch it.
No document claims more than what is built.

## 3. Reuse note
In each milestone, `docs/onboarding.md` records what generalises to other customers and domains (starter-kit
candidates) and what is specific to this hotel group. M1 candidates:
- the preflight pattern
- the NOT RUN leak scanner
- the `REQUIRE_MARKERS` guard

All three are domain-free (backlog: extract to `hotel-ai-platform`).
