# Session handoff

**Updated:** 2026-11-16, at the end of Milestone 1 (with the owner's follow-ups).

## Where things stand
- **Milestone 1 is complete.** `main` is on GitHub at
  https://github.com/vamsialladev/points-posting-investigator (public; secret scanning and push protection on;
  description, homepage and 11 topics set). Contents:
  - the spec and the approved v1 / v2 plan
  - `CLAUDE.md` (your ten standing rules) and `AGENTS.md`
  - the continuity review, fictional discovery and workflow
  - the requirements matrix (174 rows: 142 v1, 32 v2) and the tracking files
  - the preflight command, the NOT RUN leak scanner, the `REQUIRE_MARKERS` guard, and local CI
- **Checks:** results are in `docs/verification-log.md`, Milestone 1, rows 1–24.
- **Your run:** `.env` created (6 generated values, none printed); preflight `core` READY; the leak scanner reported
  NOT RUN before `.env` and "7 secret values against 45 tracked files: 0 leaks" after. Your exercise answer is in
  `docs/owner-exercises.md`.
- **Secret deny rules at the project1 level** (ADR-0008): `C:\projects\project1\.claude\settings.json` now holds 206
  deny rules for every project under project1. It is outside every repo and not committed. They were refused in this
  session: a Read of a `.env`, a `Get-Content` of a `.env`, and a Read of `.env.example`.
- **Git identity:** every commit uses `339370878+vamsialladev@users.noreply.github.com`.
- **No money spent.** Network use: PyPI packages, `git ls-remote` / `gh` for the continuity review, the gitleaks image,
  and the GitHub repo creation you approved.

## Waiting on the owner
1. **Confirm the deny rules from a fresh session** (the real test; this session loaded them as they were written).
   Use a canary, never your real `.env`, so nothing real can show if a rule fails:
   ```powershell
   New-Item -ItemType Directory -Force C:\projects\project1\deny-canary | Out-Null
   Set-Content -Path C:\projects\project1\deny-canary\.env -Value "CANARY=not-a-secret"
   ```
   Then start Claude Code in `C:\projects\project1` and ask, one at a time:
   - "Read deny-canary\.env"
   - "Run Get-Content deny-canary\.env"
   - "Run cat deny-canary/.env in Bash"

   All three must be refused, and `CANARY=not-a-secret` must never appear. Then delete the folder:
   `Remove-Item -Recurse -Force C:\projects\project1\deny-canary`. Tell me the result and I'll record it.
2. **Decide on `.env.example`:** `.env.*` also blocks every project's `.env.example`, so I can't read or edit the
   templates. M2 needs new variables in this one. Either keep it (you add template lines by hand), or let me replace
   `.env.*` with named variants (`.env.local`, `.env.bak`, `.env.production`, …), which keeps templates readable.
3. **Optional, on GitHub:** turn on Dependabot alerts for the repo, and "Block command line pushes that expose my
   email" in your account's email settings, if not already on.
4. **Milestone 2 is design-heavy.** I'll start with RFC-0001 (Kafka client and schema registry choice, outbox and relay
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
Changed: CLAUDE.md with your 10 rules, the approved v1/v2 plan, a 174-row matrix, continuity, discovery, preflight, local CI; the public repo; project1-wide deny rules.
Verified: 100 tests, local CI and gitleaks pass; your .env is READY; .env reads are refused in this session (ADR-0008).
You: test the deny rules from a fresh project1 session with the canary, choose how to treat .env.example, then I'll plan M2.
