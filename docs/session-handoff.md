# Session handoff

**Updated:** 2026-11-23. M2 PR-B1 (the outbox relay) is built and verified locally, and its PR is open. It merges
only when all five required checks pass. `main` is protected (ADR-0013), and auto-merge waits for green.

## Where things stand
- **Milestone 1 is complete** and on `main` (https://github.com/vamsialladev/points-posting-investigator, public;
  secret scanning and push protection on; `main` requires the five CI checks, admins included).
- **Milestone 2 is in progress** (RFC-0001 and its approved changes, ADR-0010 and ADR-0014):
  1. **PR-A, #3, merged:**
     - the core stack (Kafka 4.4.0, Karapace 6.2.4, Postgres 16.15)
     - the ledger mock
     - roles and migrations
     - CI
  2. **PR-B1, this PR: the outbox relay.**
     - several relays, each claiming every member's oldest open row (`FOR UPDATE SKIP LOCKED` plus a lease)
     - at-least-once publishing with trace headers
     - transient vs permanent failures, with dead-lettering after 5 permanent failures
     - `/metrics`
     - the `posting_relay` role
  3. **PR-B2, next:** the producer and the posting service, with the posting row and outbox row in one transaction.
  4. **PR-C:** retry topics and the DLQ after max attempts, corrections, the load generator and seeds, the schema
     gate, `docs/event-semantics.md`.
- **PR-B1 checks** (`docs/verification-log.md`, M2 PR-B1 #1–#16):
  - 42 real-stack tests pass; 219 offline tests pass, at 80.74% coverage; local CI 11/11
  - **Repeat runs:** 6 crash and concurrency tests passed 10/10 each
  - **The Kafka-outage test** passed 9/10 in the first batch. Run 6 left no output to examine, and the runs were
    slow because of a registry stall in the tests. After the test fixes it passed **10/10**, with 0 duplicates.
- **Changes since the plan that affect you:**
  - **One more local secret,** `RELAY_DB_PASSWORD`. I added it to your `.env` with `new_env.ps1 -AddMissing`. Nothing
    was printed, and preflight is READY.
  - **Kafka now advertises 127.0.0.1.** It used to cost every new client 2 s on IPv6.
  - **Only permanent publish failures count toward dead-lettering,** so a Kafka outage can't dead-letter good
    messages. The plan had said "after 5 failed publishes".
- **The stack is running** on your machine (with the relay). Stop it with `scripts\stack.ps1 down`, which keeps the
  data; `scripts\stack.ps1 reset` deletes it.
- **Secret deny rules at the project1 level** (ADR-0008, ADR-0009): `C:\projects\project1\.claude\settings.json`
  (outside every repo, not committed) holds 368 deny rules. Every `*.env` file is refused to Read, Edit and Write,
  and `.env.example` stays readable.
- **Git identity:** every commit uses `339370878+vamsialladev@users.noreply.github.com`.
- **No money spent.** Network use: Docker images (kafka 458 MB, karapace 1.72 GB, postgres 294 MB, python 119 MB, uv),
  PyPI packages, the version lookups, and GitHub Actions (free on a public repo).

## Waiting on the owner
1. **Nothing blocks PR-B1.** It merges with a merge commit once its five checks pass (standing rule 6, ADR-0013).
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
