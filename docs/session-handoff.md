# Session handoff

**Updated:** 2026-11-27. **Milestone 2 is complete** once PR-C (#9) merges. Auto-merge is on, held by `main`'s five
required checks. B2b merged as #8 (`41c02e3`). **Next: Milestone 3** (catalog, hypotheses, thresholds,
pre-registration). It's design-heavy, so the plan comes first and waits for the owner's OK (rule 2).

## Resume here
1. **If #9 hasn't merged:** check its five checks. If one failed, read its log, fix on `m2/pr-c`, and push.
2. **After #9 merges:** put the main checkout back on `main`, then delete the PR-C worktree (all of it is committed):
   - `git switch main`; `git pull --ff-only`
   - `git worktree remove ..\points-posting-investigator-prc`

   The main checkout is currently detached at `aa8563a` (PR-C), because only it has `.env`.
3. **Then plan M3:** the 18-scenario catalog, `docs/hypotheses.md`, `benchmarks/thresholds.yaml`, the protocol, and
   `tests/test_preregistration.py`, committed before any arm or investigator code.

## Where things stand
- **The stack is stopped.** Postgres data is kept (`pgdata`, migrated to posting 0004); Kafka's topics went with the
  container.
  - `scripts\stack.ps1 up` starts it again, `down` stops it, `reset` deletes the data.
  - Run `scripts\quiet_check.ps1` before any repeat batch.
- **Milestone 1:** complete.
- **Milestone 2:** five PRs (#3, #5, #6, #8, #9), RFC-0001 with ADR-0010 to ADR-0018.
  - the pipeline: producer, posting service, transactional outbox and relay, idempotent ledger mock
  - parking and the retry worker
  - corrections
  - seeds and the load generator
  - the schema gate
  - the semantics docs
- **Secret deny rules at the project1 level** (ADR-0008, ADR-0009): `C:\projects\project1\.claude\settings.json`
  (outside every repo, not committed).
- **Git identity:** every commit uses `339370878+vamsialladev@users.noreply.github.com`.
- **No money spent** in M2: local Docker, free GitHub Actions, no AI.

## Waiting on the owner
1. **Your OK on the M3 plan**, once it's shown. No M3 code before that.
2. **Your fresh-session canary test** is still pending on your side (verification log M1 #37).
3. **Optional, on GitHub:** turn on Dependabot alerts, and "Block command line pushes that expose my email".

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
