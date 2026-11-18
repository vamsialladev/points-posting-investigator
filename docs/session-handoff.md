# Session handoff

**Updated:** 2026-11-18. Milestone 2 PR-A (#3) is merged. This file arrives on `main` with PR #2 (the M1
follow-ups).

## Where things stand
- **Milestone 1 is complete** and on `main` (https://github.com/vamsialladev/points-posting-investigator, public;
  secret scanning and push protection on; auto-merge allowed since 2026-11-18, at your request for PR #3).
  - **PR #1** (ADR-0009) was merged without CI, as a one-time exception you approved (verification log M1 #34).
  - **PR #2** adds `tests/test_secrets_hygiene.py`. The test fails if any env-named file in the repo (say `.env.qa`)
    has no Read deny rule. It checks this repo's rules and, on your machine, the project1 rules too (M1 #35–#37).
- **Milestone 2 is in progress** (RFC-0001, `docs/rfcs/RFC-0001-pipeline-outbox-ledger.md`, ADR-0010), in three PRs:
  1. **PR-A, #3, merged 2026-11-18** with a merge commit (`b1b103f`), after all 5 CI jobs passed. Contents:
     - the core compose stack: Kafka 4.4.0, Karapace 6.2.4, Postgres 16.15, the ledger mock
     - roles and migrations for the `posting` and `ledger` databases
     - the first GitHub Actions workflow
  2. **PR-B, next:** the producer, posting service, outbox and relay.
  3. **PR-C:**
     - retries and the DLQ
     - corrections
     - the load generator and seeds
     - the schema gate
     - `docs/event-semantics.md`
- **Checks:** `docs/verification-log.md`. PR-A's results are under Milestone 2, #1–#15:
  - 31 infrastructure tests pass
  - 194 offline tests pass, with 82.82% coverage
  - local CI passes 11 of 11 steps
- **Changes from the RFC** are listed in the RFC's "Differences while building". The two that affect you:
  - **Two new local secrets,** `LEDGER_DB_PASSWORD` and `POSTING_DB_PASSWORD` (ADR-0011). I added them to your `.env`
    with `scripts\new_env.ps1 -AddMissing`, after testing it on a throwaway copy. Your existing values were kept,
    nothing was printed, and preflight `core` is READY.
  - **`localhost` is treated as 127.0.0.1** for database connections (ADR-0012). The first test run hung on IPv6.
- **The stack is stopped**, with its data kept. Your machine slowed down badly while it ran alongside the tests.
  Start it with `scripts\stack.ps1 up`; `scripts\stack.ps1 reset` deletes the data.
- **Secret deny rules at the project1 level** (ADR-0008, ADR-0009): `C:\projects\project1\.claude\settings.json`
  (outside every repo, not committed) holds 368 deny rules. Every `*.env` file is refused to Read, Edit and Write,
  and `.env.example` stays readable.
- **Git identity:** every commit uses `339370878+vamsialladev@users.noreply.github.com`.
- **No money spent.** Network use: Docker images (kafka 458 MB, karapace 1.72 GB, postgres 294 MB, python 119 MB, uv),
  PyPI packages, the version lookups, and GitHub Actions (free on a public repo).

## Waiting on the owner
1. **Nothing blocks M2 PR-B.** It merges with a merge commit once its CI is green (standing rule 6).
2. **Your fresh-session canary test** is still pending on your side (verification log M1 #37).
3. **Optional, on GitHub:** turn on Dependabot alerts, and "Block command line pushes that expose my email".

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
You: nothing for M1; M2's three-line summary comes when M2 finishes.
