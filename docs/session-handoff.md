# Session handoff

**Updated:** 2026-11-26. M2 PR-B2a (the producer and the posting service) is merged (#6, `42a4401`). B2b and PR-C
remain. The B2b plan has been shown to the owner and waits for approval; no B2b code exists yet.

## Where things stand
- **Milestone 1 is complete** and on `main` (https://github.com/vamsialladev/points-posting-investigator, public;
  secret scanning and push protection on; `main` requires the five CI checks, admins included, ADR-0013).
- **Milestone 2 is in progress** (RFC-0001 and its approved changes; ADR-0010, ADR-0014, ADR-0015):
  1. **PR-A, #3, merged:** the core stack (Kafka 4.4.0, Karapace 6.2.4, Postgres 16.15), the ledger mock, roles and
     migrations, CI.
  2. **PR-B1, #5, merged:** the outbox relay. Several relays each claim every member's oldest open row; publishing
     is at least once; permanent failures are dead-lettered; `/metrics`; the `posting_relay` role.
  3. **PR-B2a, #6, merged 2026-11-26:**
     - the producer (headers `event_id`, `schema_version`, `correlation_id`, `traceparent`; keyed by member)
     - the posting service:
       - credits the ledger under the business key `stay_id:revision`
       - writes the posting row and its outbox row in **one transaction**
       - commits the Kafka offset only after it
       - seeks back on database, ledger or dead-letter-topic failures
       - dead-letters events that can never post, with their original bytes
     - the `posting` container
  4. **PR-B2b, next (plan waiting for your OK):**
     - the parking table and retry worker (backoff, max attempts, then the dead-letter topic)
     - per-member order under retries
     - the retry topics removed
  5. **PR-C:** corrections (revision > 1), the load generator and seeds, the schema gate, `docs/event-semantics.md`.
- **PR-B2a checks** (`docs/verification-log.md`, M2 PR-B2a #1–#9):
  - 275 offline tests pass (80.40% coverage); 53 real-stack tests pass; local CI 11/11
  - **Repeat runs on the final code:** 8 crash and concurrency tests passed 10/10 each
    (`docs/evidence/m2-pr-b2a-repeat-runs.md`)
  - PR #6's five CI checks passed before auto-merge
- **What B2a still does that B2b changes:**
  - a transient ledger failure is retried in place, so its partition waits
  - a permanent ledger refusal (409, other 4xx) is dead-lettered at the first attempt
- **The stack is stopped**, with its data kept. Start it with `scripts\stack.ps1 up`; stop it with
  `scripts\stack.ps1 down`; `scripts\stack.ps1 reset` deletes the data.
- **Secret deny rules at the project1 level** (ADR-0008, ADR-0009): `C:\projects\project1\.claude\settings.json`
  (outside every repo, not committed) holds 368 deny rules. Every `*.env` file is refused to Read, Edit and Write,
  and `.env.example` stays readable.
- **Git identity:** every commit uses `339370878+vamsialladev@users.noreply.github.com`.
- **No money spent.** Network use: Docker images, PyPI packages, the version lookups, and GitHub Actions (free on a
  public repo).

## Waiting on the owner
1. **Approve, or change, the B2b plan.** No B2b code until you do.
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
