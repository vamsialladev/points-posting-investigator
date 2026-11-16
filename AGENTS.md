# Stage 10: AI Points-Posting Incident Investigator (portfolio simulation)

Guidance for Codex and other coding agents. Fictional hotel group, synthetic data, simulated people.

**One shared standard.** `CLAUDE.md` holds the project rules. This file points to the same rules and must not
contradict them; if it does, `CLAUDE.md` and `docs/MASTER-SPEC.md` win. Source of truth: `docs/MASTER-SPEC.md`.
Claude Code is the builder (ADR-0001). The spec's Codex session kit (Appendix A) is kept as an **optional exercise**:
log any Codex run in `docs/verification-log.md` with the task, the time to a verified result, defects found and tests
passed.

Every session: read `docs/implementation-status.md` and `docs/session-handoff.md`; run `make test` (or
`scripts\test.ps1`); work only on the named milestone; run its "done when" checks; review the diff; update
`docs/requirements-matrix.md`, `docs/implementation-status.md`, `docs/verification-log.md` and
`docs/session-handoff.md`; commit (never push without the owner's OK).

Rules:
- Part 0 honesty rules are non-negotiable. Never weaken tests. A check that tests nothing must fail.
- AI is read-only. Recovery is deterministic Python and human-approved by someone other than the requester.
- Never open or print `.env`.
- No paid resources, deploys, publishing, real messages or pushes without the owner's explicit OK.
- Record which tool did each piece of work.
- Commits use `339370878+vamsialladev@users.noreply.github.com`.

Before each milestone, say whether it is design-heavy (Milestones 2, 3, 6, 7, 9, 10) so the owner can choose a
higher reasoning setting and approve the plan first.
