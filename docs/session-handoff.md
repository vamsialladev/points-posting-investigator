# Session handoff

**Updated:** 2026-11-16, at the end of Milestone 1.

## Where things stand
- **Milestone 1 is complete and committed on `main`** (local only: there is no GitHub repo yet). Contents:
  - the spec and the approved v1 / v2 plan
  - `CLAUDE.md` (your ten standing rules) and `AGENTS.md`
  - the continuity review, fictional discovery and workflow
  - the requirements matrix (every spec requirement tiered v1 or v2) and the tracking files
  - the preflight command, the NOT RUN leak scanner, the `REQUIRE_MARKERS` guard, and local CI
- **Checks:** results are in `docs/verification-log.md`, Milestone 1.
- **Git identity:** repo-local `user.email` is `339370878+vamsialladev@users.noreply.github.com`. Every commit so far
  uses it (verification log).
- **No money spent, no accounts used, no network calls except** `uv` downloading packages from PyPI, `git ls-remote`
  and `gh repo list` for the continuity review, and Docker pulling the pinned gitleaks image.

## Waiting on the owner
1. **Create your `.env`** (generates local random values, prints none):
   ```powershell
   cd C:\projects\project1\points-posting-investigator
   powershell -ExecutionPolicy Bypass -File scripts\new_env.ps1
   powershell -ExecutionPolicy Bypass -File scripts\preflight.ps1 -Profile core
   ```
   Preflight should say `Result: READY`. Leave `ANTHROPIC_API_KEY` empty: mock AI is the default, and a live run
   needs your OK and a cap first.
2. **Confirm Claude Code can't read `.env`:** start Claude Code inside this folder (not the parent) and ask it to read
   `.env`. It must be refused (`.claude/settings.json`). Tell me the result and I'll record it.
3. **Decide on the GitHub repo:** may I create `vamsialladev/points-posting-investigator` as a **public** repo and push
   `main`? Until then, milestones merge locally with `--no-ff`. Once it exists, I'll turn on secret scanning and push
   protection, as for Stage 9.
4. **Milestone 2 is design-heavy.** I'll start by writing RFC-0001 (Kafka client and schema registry choice, outbox
   and relay semantics, ledger idempotency, test plan on real Kafka and Postgres) and wait for your approval before
   any code.

## Milestone 1, in teaching-note form (spec Part N)
- **What changed.** The repo has its rules, its plan and a safe way to check settings, but no product yet.
- **Why.** The spec's honesty rules only work if they are enforced from day one:
  - preflight never prints a value
  - a scan of nothing fails
  - every requirement has a release and a status that a test checks
- **How to verify:** `scripts\test.ps1`, `scripts\ci_local.ps1`, `scripts\preflight.ps1 -Profile core`.
- **Failure modes seen:**
  - A test that passed while checking nothing: `-m` deselection happened after my hook counted the tests. Its own
    test caught it.
  - A false "leak": the fake value `points` also appears in normal report text.
- **Exercise for you:** run `scripts\leaks.ps1` before and after you create `.env`, and explain why the first run
  fails even though nothing leaked (hint: ADR-0007).

## Milestone 1 in three lines
Changed: the repo now has CLAUDE.md with your 10 rules, the approved v1/v2 plan, a 173-row requirements matrix (141 v1, 32 v2), continuity, fictional discovery, preflight and local CI.
Verified: tests, lint, types, the dependency audit and gitleaks pass locally (see the verification log); nothing is pushed or deployed.
You: run `scripts\new_env.ps1`, check that Claude Code is refused `.env`, and say whether I may create the public GitHub repo; M2's design plan comes next.
