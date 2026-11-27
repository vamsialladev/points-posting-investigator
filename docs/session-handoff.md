# Session handoff

**Updated:** 2026-11-27. M2 PR-B2b passed its 10× batch on a quiet machine (140/140, verification log M2 PR-B2b #28)
and is pushed as a PR, auto-merging when CI is green. PR-C is being built on `m2/pr-c` (worktree
`..\points-posting-investigator-prc`); its real-stack tests wait until the owner says the machine is free.

## Resume here (B2b)
1. `git switch m2/parking-retry`; `scripts\stack.ps1 up` (9 services, incl. `retry-worker` and Kafka's test-only
   `FAULTS` listener on `127.0.0.1:19093`).
2. **Quiet check:**
   `powershell -ExecutionPolicy Bypass -File scripts\quiet_check.ps1 -Minutes 5 -Out docs\evidence\m2-pr-b2b-quiet-check.md`.
   Go on only if it says QUIET (exit 0); record it either way.
3. **The 10× batch**, no code edits while it runs:
   `scripts\repeat_tests.ps1 -Times 10 -Out docs\evidence\m2-pr-b2b-repeat-runs-final.md`, with these tests:
   - the B2b parking tests: `poison_event_is_retried`, `per_member_order_holds_while_the_first`,
     `crash_after_parking`, `worker_crash_after_the_credit`, `db_failure_inside_the_worker`,
     `two_workers_never_claim`, `long_ledger_outage_never`, `ledger_outage_parks_the_event`
   - B2a's `eight_concurrent_copies` and `eight_concurrent_resends`
   - the producer tests: `topic_that_does_not_exist`, `unreachable_broker`, `producer_retries_add_no_duplicates`,
     `without_idempotence`

   Busy runs are flagged and re-run, never counted. Any failure means finding the cause before any PR.
4. Add the results to the verification log (M2 PR-B2b, after #20). Then push, open the PR, wait for its five CI
   checks, and auto-merge only when green. Stop the stack with `scripts\stack.ps1 down`.

**What B2b changed** (verification log M2 PR-B2b #1–#20):
- **Parking (ADR-0016):** parking table, retry worker, per-member order, retry topics removed.
- **Producer silent loss found and fixed (ADR-0017; incident `docs/incidents/2026-11-26-producer-silent-loss.md`):**
  the old producer reported success for events Kafka never took. Under fault injection the fixed producer gave
  0 duplicates; without idempotence, the same fault gave 37.
- **Offset-commit failure:** now a warning plus a metric, and the consumer keeps going.
- **A new repeat script and quiet check.**
- **Offline:** 311 tests pass, 81.31% coverage.
- **Batch 1 was on the old code and a busy machine:** 4 tests at 9/10. Not yet repeated on the final code.

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
  4. **PR-B2b, built on `m2/parking-retry`, waiting for the 10× batch (see "Resume here"):**
     - the parking table and retry worker (backoff, max attempts, then the dead-letter topic)
     - per-member order under retries
     - the retry topics removed
     - the producer silent-loss fix and offset-commit failure handling
  5. **PR-C:** corrections (revision > 1), the load generator and seeds, the schema gate, `docs/event-semantics.md`.
- **PR-B2a checks** (`docs/verification-log.md`, M2 PR-B2a #1–#9):
  - 275 offline tests pass (80.40% coverage); 53 real-stack tests pass; local CI 11/11
  - **Repeat runs on the final code:** 8 crash and concurrency tests passed 10/10 each
    (`docs/evidence/m2-pr-b2a-repeat-runs.md`)
  - PR #6's five CI checks passed before auto-merge
- **What B2b changes in B2a (once merged):**
  - a transient ledger failure parks the event instead of holding up its partition
  - a permanent refusal is retried up to 5 times before the dead-letter topic; a 409 is dead-lettered at once
- **The stack is running** while B2b waits for its batch (see "Resume here"). Start it with `scripts\stack.ps1 up`; stop it with
  `scripts\stack.ps1 down`; `scripts\stack.ps1 reset` deletes the data.
- **Secret deny rules at the project1 level** (ADR-0008, ADR-0009): `C:\projects\project1\.claude\settings.json`
  (outside every repo, not committed) holds 368 deny rules. Every `*.env` file is refused to Read, Edit and Write,
  and `.env.example` stays readable.
- **Git identity:** every commit uses `339370878+vamsialladev@users.noreply.github.com`.
- **No money spent.** Network use: Docker images, PyPI packages, the version lookups, and GitHub Actions (free on a
  public repo).

## Waiting on the owner
1. **A quiet machine** for B2b's 10× batch. You're coordinating the other sessions; the batch starts only after a
   5-minute QUIET result.
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
