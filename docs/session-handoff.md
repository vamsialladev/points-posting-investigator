# Session handoff

**Updated:** 2026-11-17, Milestone 1 follow-ups (ADR-0009).

## Where things stand
- **Milestone 1 is complete.** `main` is on GitHub at
  https://github.com/vamsialladev/points-posting-investigator (public; secret scanning and push protection on;
  description, homepage and 11 topics set). Contents:
  - the spec and the approved v1 / v2 plan
  - `CLAUDE.md` (your ten standing rules) and `AGENTS.md`
  - the continuity review, fictional discovery and workflow
  - the requirements matrix (174 rows: 142 v1, 32 v2) and the tracking files
  - the preflight command, the NOT RUN leak scanner, the `REQUIRE_MARKERS` guard, and local CI
- **Checks:** results are in `docs/verification-log.md`, Milestone 1, rows 1–33.
- **Your run:** `.env` created (6 generated values, none printed); preflight `core` READY; the leak scanner reported
  NOT RUN before `.env` and "7 secret values against 45 tracked files: 0 leaks" after. Your exercise answer is in
  `docs/owner-exercises.md`.
- **Secret deny rules at the project1 level** (ADR-0008, ADR-0009): `C:\projects\project1\.claude\settings.json`
  (outside every repo, not committed) now holds 368 deny rules for every project under project1.
  - **Confirmed in a fresh session (2026-11-17):** Read, `Get-Content` and Bash `cat` of a `.env` were all refused.
  - **Gap found and closed:** `prod.env` was open to the Read tool. Every file ending in `.env` is now refused to Read,
    Edit and Write.
  - **Template readable:** `.env.example` reads normally again (named variants replace `.env.*`).
  - `tests/test_env_template.py` fails if `.env.example` ever holds a real-looking value.
- **Git identity:** every commit uses `339370878+vamsialladev@users.noreply.github.com`.
- **No money spent.** Network use: PyPI packages, `git ls-remote` / `gh` for the continuity review, the gitleaks image,
  and the GitHub repo creation you approved.

## Waiting on the owner
1. **Merge the ADR-0009 pull request, or say whether I may merge it without CI.** The repo has no CI yet (M2), and the
   standing rule is to merge only on green CI. The local checks all pass.
2. **Optional, on GitHub:** turn on Dependabot alerts for the repo, and "Block command line pushes that expose my
   email" in your account's email settings, if not already on.
3. **Milestone 2 is design-heavy.** I'll start with RFC-0001 (Kafka client and schema registry choice, outbox and relay
   semantics, ledger idempotency, the test plan on real Kafka and Postgres, the first CI workflow) and wait for your
   approval before any code.

## Milestone 1, in teaching-note form (spec Part N)
- **What changed.** The repo has its rules, its plan, a safe way to check settings, and a public home, but no product
  yet.
- **Why.** The spec's honesty rules only work if they are enforced from day one:
  - preflight never prints a value
  - a scan of nothing fails
  - every requirement has a release and a status that a test checks
- **How to verify:** `scripts\test.ps1`, `scripts\ci_local.ps1`, `scripts\preflight.ps1 -Profile core`.
- **Failure modes seen:**
  - A test that passed while checking nothing: `-m` deselection happened after my hook counted the tests. Its own
    test caught it.
  - A false "leak": the fake value `points` appears in normal report text.
  - gitleaks exiting 0 on an empty history.
  - A broad deny pattern (`.env.*`) that also blocks a safe file.
- **Exercise:** done (`docs/owner-exercises.md`).

## Milestone 1 in three lines
Changed: CLAUDE.md with your 10 rules, the v1/v2 plan, a 174-row matrix, continuity, discovery, preflight, local CI, the public repo; project1 deny rules now block every *.env file while .env.example stays readable and tested.
Verified: all tests, local CI and gitleaks pass; your .env is READY; a fresh project1 session refused every .env probe (ADR-0008, ADR-0009).
You: merge the ADR-0009 pull request (no CI exists yet), then I'll write the M2 design plan and wait for your OK.
