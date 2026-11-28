# Session handoff

**Updated:** 2026-11-28 (UTC). **RFC-0002 Phase 1 is done and Phase 2 is done except Kafka SASL and ACLs.** All 18
scenarios trigger and reset on a real stack in GitHub Actions (6 in the required CI job, 12 in the "Scenario batch"
workflow). Merged: PRs #11 to #16. Open: #17 (Kafka logins and the access list). Milestone 2
is complete. The owner's "Milestone 3" (a read-only AI investigator plus human-approved replay) runs as the phases of
`docs/rfcs/RFC-0002-investigator-and-approved-replay.md` across spec M3, M6 and M7 (ADR-0019).

## Start of the next session
1. Read `CLAUDE.md`, `docs/implementation-status.md`, this file, **RFC-0002** and `docs/failure-catalog.md`.
2. Run `scripts\test.ps1`: it should give **575 passed, 91 skipped**, coverage 83.46% (after PR #14).
3. Continue with the first phase below that isn't done. The plan is approved: no new approval is needed for a
   phase, only for what "Standing orders" lists.

## Standing orders from the owner (2026-11-27, latest version; they replace the earlier ones)
Speed:
1. Work straight through. Don't wait between steps unless a rule below requires it.
2. Decide routine choices yourself and record them in an ADR. Batch any questions into one message, each with a
   recommended answer, and keep working on everything else while waiting.
3. Within an already approved cap: re-run flagged or killed runs, and fix your own script or test bugs, without
   asking. Log each one in the verification log.
4. **Run real-stack and Docker work in GitHub Actions instead of on the laptop wherever possible,** so it can run in
   parallel. The "Scenario batch" workflow does this for the slow scenarios.
5. **The laptop is shared** (Stage 9's M13, Stage 11's benchmarks). Before any local benchmark or Docker stack, the
   owner must have said "machine is free" for this session. `scripts\quiet_check.ps1` alone is never enough.
   Benchmarks go one at a time. Afterwards bring the stack down and keep the data. Work only in this repo's folder.
6. Merge on green with auto-merge. Fix failing CI yourself and push again.
7. Keep this file current after every milestone step.

Quality (never skip):

8. **Ask before:** new paid spend or raising a cap, deploys, publishing or making anything public, deleting data,
   changing secrets or Cloud Run/Neon, or weakening any test, gate or branch protection.
9. Never invent results, numbers or passes. Never print or commit secrets.
10. Run the relevant guard tests locally before pushing (the compose and workflow parse tests, the pre-registration
    tests, and so on).
11. **Never use shell heredocs; edit files with the file tools only** (`CLAUDE.md`, Windows notes).
12. Report in 5 lines: done, numbers, spend against the cap, what's next, and what is needed from the owner (or
    "nothing").

Already approved:
- **The live run (Phase 7):** a hard cap of **$3**. Before it: re-check Haiku 5.5's price on Anthropic's official
  pricing page, redo the estimate, and show it to the owner.
- **New local passwords in `.env`** through `scripts\new_env.ps1 -AddMissing` (database roles and Kafka identities).

## RFC-0002 phases
| Phase | Content | State |
|---|---|---|
| 0 | RFC-0002, ADR-0019 | done (`49dc098`) |
| 1 | Pre-registration: catalog, hypotheses, thresholds, protocol, lock, order test | done (`4828940`), PR #11 |
| 2 | Trigger and reset for all 18 scenarios (`python -m app.scenarios`); `log_event`, `change_event`, the lag reader, alert rules as YAML; Kafka SASL and ACLs | **in progress**: see "Phase 2, piece by piece" |
| 3 | Minimal rules baseline (`app/arms/`) | not started. **The first commit here freezes the pre-registration** |
| 4 | Investigator (`app/investigator/`): tools, loop, citations, mock and hostile-mock providers, audit, GenAI spans | not started |
| 5 | Proposal, approval bound to the message-set hash, replay through the idempotent path | not started |
| 6 | Mock evaluation of the 18 dev scenarios, evidence, teaching notes | not started |
| 7 | One live run, cap $3 | not started; see "Standing orders" |

**Before Phase 3's first commit,** any correction to a pre-registered file needs
`uv run python scripts/prereg_lock.py --write` in the same commit. After it, those files don't change.

## Phase 2, piece by piece
| Piece | State |
|---|---|
| Plans for all 18 scenarios as pure data (`app/scenarios/`: `catalog.py`, `steps.py`, `plans.py`); `python -m app.scenarios list` and `plan <id> [--run N] [--pair A]` | done, merged (PR #13). Every (scenario, run) owns 50 members (GR-30000 up) and 80 stays (BR/ML-0100 up); runs 0 to 12 |
| Lag calculation and a read-only reader (`app/ops/lag.py`); alert rules (`ops/alert-rules.yaml`) and evaluator (`app/ops/alerts.py`) | done, merged (PR #13) |
| The `ops` database (`app/ops/tables.py`, `migrations/ops/`): `log_event`, `change_event`, `member_question`, `alert_evaluation`, `runbook_section`; the insert-only role `ops_app`; the log handler `app/ops/logsink.py`, installed by the four services | done, merged (PR #14); the role's rights verified on real Postgres in CI. `OPS_DB_PASSWORD` is in the owner's `.env` (added 2026-11-27 with `new_env.ps1 -AddMissing`; preflight `core` READY) |
| The executor (`executor.py`), the local-stack adapter (`stack.py`, `kafka_io.py`), `trigger` and `reset` with a manifest in `.scenario-runs/` (`run.py`), `scripts\scenario.ps1`, `LEDGER_TIMEOUT_SECONDS` | done, merged (PR #14). S01, S02, S05, S11, S13 and S16 triggered and reset on CI's stack (`tests/test_scenarios_real.py`; 91 real-stack tests passed, run 46058085179) |
| The other 12 scenarios on a real stack (S03, S04, S06 to S10, S12, S14, S15, S17, S18) | **done in GitHub Actions** (owner's order 4): `tests/test_scenarios_batch.py`, the "Scenario batch" workflow (`.github/workflows/scenario-batch.yml`, not a required check), PR #16. Results: verification log M3 Phase 2 and `docs/evidence/m3-scenario-batch-ci-run-*.txt`. Locally it is `scripts\test_integration.ps1 --batch` with the stack up, and only after the owner says "machine is free"; a local run is optional now |
| Kafka SASL and ACLs, in its own PR | **PR #17, open; auto-merge only after its CI and its batch run are both green.** First real-stack run (2026-11-28): the stack started healthy with logins, the batch passed (14), the required job passed 99 of 100; the broker refused every investigator write, commit, topic creation and ACL change. The one failure was a bug in the test that compares the broker's access list with the code's (fixed, to be confirmed by the next run). After it merges: run `scripts\new_env.ps1 -AddMissing` (approved) so the owner's local stack can start; the Kafka container must be recreated, which loses nothing that matters (it has no volume). The older notes follow. Done there: `app/pipeline/kafka_auth.py` (one settings function per identity; the access list as data, the investigator describe and read only), every app and test client wired to it, `topics.ensure_acls`. Also done there, **never yet run on a stack**: the broker's SASL listeners, authorizer and super users in `docker-compose.yml` (the controller listener stays plain, as in Apache Kafka's own single-node example), Karapace's login, each service given only its own login, the seven `KAFKA_*_PASSWORD` names in the template, `new_env.ps1`, preflight and `ci.yml`, offline checks of all that, and `tests/test_kafka_acls_real.py` (the broker refuses an investigator's produce, offset commit, topic creation and ACL change). **Still to do:** merge `main` in (this PR's files changed under it); add the seven names to `scenario-batch.yml` and make `scripts/run_integration.py` pass them from `.env` to the tests; ADR-0021; open the PR and fix whatever its CI and batch runs show (expect several rounds: the broker settings come from the docs, not from a run); then `scripts\new_env.ps1 -AddMissing` on the owner's machine (approved) so the local stack can start. Kafka docs source used: `apache/kafka` tag 4.4.0, `docs/security/*.md` and `docker/examples/docker-compose-files/single-node/sasl_plaintext` |

**The stack on this machine was created before the `ops` database existed.** The next `scripts\stack.ps1 up`
rebuilds the image and `db-init` creates and migrates `ops`; no data is deleted.

## Design notes for Phase 2
- **S07** takes the posting role's login away instead of pausing Postgres, so the ledger's database stays up.
- **S12** changes the ledger timeout of the posting service **and** the retry worker (otherwise the worker's normal
  timeout would post the parked events at once), and writes the change record first.
- **S03 takes about a minute to trigger:** each timed-out event costs the single-threaded consumer about 16 s (a 5 s
  timeout, two 5 s lookups, the settle time).
- **Test runs use the top run numbers** (12 down to 6) and pick the first one that left nothing on the stack; demo
  runs count up from 0. When all are used, `scripts\stack.ps1 reset` clears them: that deletes data, so ask first.
- **The adapter never writes a posting, outbox row, parked event or credit.** It writes only the scenario's own
  evidence rows in `ops`, and the reset deletes only the runbook line its trigger planted (by tag).
- **Never edit a file through a shell heredoc here.** One turned a backslash into a line break inside
  `docker-compose.yml` and only CI caught it (verification log M3 Phase 2 #9). The owner's rule since then: file
  tools only. `tests/test_compose_file.py` now parses the compose file offline.
- **S13's evidence is on the topic only.** The posting row has no `occurred_at`, so the investigator's `get_events`
  (Phase 4) must return an event's `occurred_at` next to the broker's timestamp. No test asserts that evidence yet.
- **A CI-only timing race was found and fixed** (PR #12): tests that need the retry worker to reach a fault point
  must use `first_claim(worker)`, never a single `run_once()` straight after parking.
- **Replay (Phase 5):** the posting service reports an already-parked event ID as a duplicate, so a dead parked
  event is replayed by re-opening it for the retry worker, not by sending it to the main topic again.
- **The investigator reads the ledger's database, never its API,** so it never holds the token that can credit.
- **Kafka** has no authentication today (all listeners PLAINTEXT). SASL changes every service's connection and
  adds local passwords through `scripts\new_env.ps1 -AddMissing`.

## What M3 originally had to deliver (from `docs/implementation-plan.md`, row 3; the first block is now done)
- **Pre-registration first, in its own commit, before any arm or investigator code exists:**
  - `docs/failure-catalog.md` (all 18 scenarios)
  - `docs/hypotheses.md` (H1–H5 from spec H3, plus cases where the rules alone are enough, named in advance)
  - `benchmarks/thresholds.yaml`
  - `docs/benchmark-protocol.md` (metrics with denominators, leakage-proof splits, ≥60 incidents, held-out = the
    decision split, no tuning on held-out)
  - `tests/test_preregistration.py`, which checks with `git log` that these come before anything under `app/arms/` or
    `app/investigator/`, and that the YAML matches the doc
- **Then a trigger and a reset command for every scenario**, deterministic.
- **The ledger `members` table** moved to v2 (ADR-0019): none of the 18 scenarios needs it.

## What M2 already gives each scenario (spec Part C), and what's missing
Each scenario needs a trigger, the evidence it leaves, and a reset.

| # | Scenario | Already there | Missing (M3 unless noted) |
|---|---|---|---|
| 1 | Invalid schema | posting dead-letters undecodable and unknown-`schema_version` events (`error_class` `schema` / `schema_version`); the schema gate refuses a breaking change | a trigger CLI that sends bad bytes |
| 2 | Duplicate delivery | `loadgen --duplicates`; the `DUPLICATE` outcome in `posting_events_total` | trigger and reset wrappers |
| 3 | Ledger timeout | ledger `/control/settings` `latency_ms`; status lookup before any retry; parks as transient | a trigger that sets latency above the client timeout |
| 4 | Ledger 429 | `/control/settings` `rate_per_sec` / `burst`; `Retry-After` honoured; parks as transient | trigger wrapper |
| 5 | Poison → DLQ | permanent ledger 422 (points over the limit), dead-lettered after 5 attempts with D8 headers | trigger wrapper |
| 6 | Consumer crash | `docker compose restart posting`; offsets commit after the transaction | trigger wrapper; the in-process fault hooks are test-only |
| 7 | DB transaction failure | test-only fault hook (`mid_transaction`) | a stack-level trigger (for example, pausing Postgres) |
| 8 | Expired credential 401 | `/control/settings` `token_expires_at`, repaired with `clear_token_expiry` | trigger and reset wrappers |
| 9 | Backlog and lag | ledger latency plus `loadgen --rate` | **a consumer-lag metric for the posting group** (RFC-0001 test 14; M4 at the latest) |
| 10 | Outbox relay stopped | `docker compose stop relay`; `outbox_unpublished_rows` grows | trigger and reset wrappers |
| 11 | Correction before original | built: `original_missing`, dead-lettered after 5 attempts (`test_posting_kafka.py`) | trigger: `loadgen` with a correction only |
| 12 | Recent config change | nothing yet | **the "what changed" feed is M4**; M3 records a config-change event that it can read |
| 13 | Clock skew | nothing yet | how "waiting period" decisions use time (Stage 9's `expected_post_at_utc`) |
| 14 | Rebalance storm | one rebalance is tested | a storm trigger (consumers joining and leaving repeatedly) |
| 15 | Compound incident | any two of the above | composition rules in the catalog |
| 16 | Insufficient evidence | — | a design where the stored evidence genuinely can't decide |
| 17 | Prompt injection in a log | — | **structured logs in Postgres are M4**; M3 only defines the text and where it lands |
| 18 | Noisy alert, no incident | — | **alert rules are M4**; M3 defines the noise |

Evidence that exists now:
- **Rows** (posting database): `posting`, `outbox` (status, attempts, `last_error`), `parked_event` (original bytes,
  `error_class`, attempts, transient failures, times) and `skipped_event`. The ledger database has `credits`.
- **The DLQ topic** `stay.checked_out.dlq`: original bytes plus `error_class`, `error_detail`, `attempt`,
  `original_*`, `first_failed_at` and `last_failed_at`.
- **Metrics:**
  - posting `:9109`: `posting_events_total{outcome}`, `posting_dlq_messages_total{error_class}`,
    `posting_retries_total{reason}`, `posting_parked_total{reason}`, `posting_offset_commit_failures_total{error}`,
    `posting_ledger_request_seconds`
  - retry worker `:9110`: `posting_parked_open`, `posting_parked_dead`, `posting_parked_oldest_age_seconds`,
    `retry_outcomes_total{outcome}`
  - relay `:9108`: `outbox_unpublished_rows`, `outbox_dead_rows`, `outbox_published_total`,
    `outbox_publish_failures_total{error_class}`, `outbox_dead_lettered_total`
- **Trace context:** `traceparent` in Kafka headers and the outbox.
- **Not yet:** OpenTelemetry export, structured logs in Postgres, Prometheus and Grafana, alert rules, the "what
  changed" feed. All of these are M4.

## End state of M2
- **Code on `main`:**
  - producer (ADR-0017)
  - posting service (ADR-0015)
  - outbox relay (ADR-0014)
  - parking and the retry worker (ADR-0016)
  - corrections (ADR-0018)
  - `seed.py`, `loadgen.py`, `schema_check.py`
  - the ledger mock
  - migrations: posting 0001–0004, ledger 0001

  How it all behaves: `docs/event-semantics.md` and `docs/architecture.md`.
- **Tests:** 358 offline; 68 real-stack (`scripts\stack.ps1 up`, then `scripts\test_integration.ps1`). Every crash and
  concurrency test passed 10/10 on a quiet machine (`docs/evidence/m2-pr-b2b-repeat-runs-final.md`,
  `m2-pr-c-repeat-runs*.md`).
- **Requirements matrix:** v1 has 142 rows, 44 implemented and verified, 98 planned.
  - **Still open from M2's area:** TEST-02's trace propagation (M4).
  - **Tech debt:** `docs/tech-debt-register.md`, 7 items.
- **CI:** the five required checks on `main` (ADR-0013). The schema gate is a step inside "Real Kafka, Karapace and
  Postgres".
- **The local machine:**
  - **Stack:** stopped. Postgres data is kept (`pgdata`, posting at migration 0004); Kafka has no volume, so topics
    go when the container does (`stack.ps1 up` recreates the pipeline topics).
  - **Checkout:** clean, on `main`, with no other worktree. Local branches already merged into `main` are still
    there (`m2/*`); delete them only with the owner's OK.
  - **`.test-logs\`:** git-ignored full run logs.
- **No money spent** in M2: local Docker, free GitHub Actions, no AI.

## How to work here (lessons from M2)
- **Repeat runs:** before any 10× batch, run `scripts\quiet_check.ps1 -Minutes 5` and start only on QUIET. Never edit
  code in the checkout while a batch runs; use a git worktree for parallel work.
- **Real-stack runs need `.env`:** only the main checkout has it, and it must never be copied or read. To run another
  branch's real-stack tests, detach the main checkout at that branch.
- **Pushing:** `git -c credential.helper= -c "credential.helper=!gh auth git-credential" push`. Auto-merge goes on
  with `gh pr merge <n> --auto --merge` (the app's auto-merge tool can't match this repo); `main`'s protection holds
  it until green.
- **Other sessions share this machine.** Ask the owner before any long real-stack batch.

## Waiting on the owner
1. **Your OK before each real-stack batch** (Phases 2, 4 and 5), and your look at the re-checked cost estimate before
   the live run.
2. **Your fresh-session canary test** is still pending on your side (verification log M1 #37).
3. **The M2 exercise** in `docs/owner-exercises.md`.
4. **Optional, on GitHub:** turn on Dependabot alerts, and "Block command line pushes that expose my email".

## Milestone 2, in teaching-note form (spec Part N)
- **What changed.** A checkout event travels from a simulated property system through Kafka to an idempotent ledger,
  and on to `points.posted`:
  - **Never silently lost:** the producer reports every delivery failure.
  - **Never credited twice:** the ledger key is `stay_id:revision`, with `UNIQUE` in the database.
  - **In order per member:** parking keeps order without blocking a partition.
  - **Corrections credit only the difference.**
- **Why.** M3's failure scenarios and M6's investigator need a pipeline that fails in realistic, recorded ways. Every
  failure path writes stored rows (parked, skipped, dead-lettered), so the investigator can cite them.
- **How to verify:**
  - `scripts\test.ps1`: 358 offline tests
  - `scripts\stack.ps1 up`, then `scripts\test_integration.ps1`: 68 real-stack tests
  - `scripts\repeat_tests.ps1 -Times 10` on a quiet machine
  - results: `docs/verification-log.md`, M2 sections
- **Failure modes seen:**
  - **The producer reported success for events Kafka refused** (ADR-0017, incident 2026-11-26). Found only by
    10-times repeat runs.
  - **A test can pass for the wrong reason:** the rebalance test sometimes ran without a rebalance. Its guard caught
    it (6/10), and the setup was fixed.
  - **A busy machine makes timing tests fail:** a 70-minute run had 7 failures from load. Hence the quiet check, and
    flagged runs that aren't counted.
  - **The stack's own health checks used 22.8% of the machine** until slowed down.
  - **Random stay IDs collided** in the synthetic data.
- **Exercise:** in `docs/owner-exercises.md` (M2).

## Milestone 2 in three lines
Changed: the full points pipeline (producer, posting service, outbox and relay, idempotent ledger, parking, corrections, load generator, schema gate) over 5 PRs, and a producer silent-loss bug found by repeat runs and fixed.
Verified: 358 offline and 68 real-stack tests pass; on a quiet machine, 140/140 B2b repeat runs plus PR-C's new tests 10/10 each (the rebalance test after a setup fix); idempotent producer 0 duplicates vs 33–120 without; $0 spent.
You: approve the M3 plan when I show it; your canary test is still pending; optional GitHub settings.

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
