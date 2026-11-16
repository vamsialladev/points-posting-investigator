# Verification log

Real results only, newest milestone first. Each row: what was checked, the exact command, and the result. Tool: Claude
Code (Opus 5.5) did all of Milestone 1.

## Milestone 1 (2026-11-16)
| # | Check | Command | Result |
|---|---|---|---|
| 1 | Workspace before any change | `Get-ChildItem -Force`; `git status` | `.git` (branch `master`, no commits) and an empty `docs/`. The owner then added `docs/MASTER-SPEC.md` (32,818 bytes); nothing else existed, so nothing to preserve beyond it |
| 2 | Live site vs the site repo | fetch `https://vamsialla.com/data/projects.json?cb=<random>`; compare with `vamsi-portfolio/data/projects.json` (CR stripped) | identical, 8,363 bytes; site repo `main` at `7a2cfe7`; stages PS, 0–8; no Stage 9 |
| 3 | Public repos and their versions | `gh repo list vamsialladev`; `git ls-remote https://github.com/vamsialladev/<repo>.git HEAD` | 16 repos (15 public); SHAs in `docs/continuity.md` §1; no `points-posting-investigator` repo |
| 4 | Stage 9 read, not modified | read-only `Read`/`Grep` of the files in `docs/continuity.md` §1 | no write to Stage 9 |
| 5 | Branch and identity | `git symbolic-ref HEAD refs/heads/main`; `git config user.email` | branch `main`; `339370878+vamsialladev@users.noreply.github.com` (repo-local) |
| 6 | First test run found two defects in my own code, both fixed before commit | `uv run pytest -q -rs` | (a) `REQUIRE_MARKERS` counted tests before `-m` deselection: `test_deselecting_every_required_test_fails_too` failed; fixed by counting at `pytest_collection_finish`. (b) the leak test flagged a non-leak: the fake user `points` appears in report text; fixed with distinctive fake values |
| 7 | Offline checks | `scripts\test.ps1` | ruff clean; 29 files formatted; mypy: no issues in 4 source files; **100 passed**; coverage **98.96%** (gate 80%) |
| 8 | The guard tests check real sets, not empty ones | count via `tests.test_repo_guidance.matrix_rows()` | 173 matrix rows (141 v1, 32 v2); 17 `tests/…::name` evidence references and 29 implementation paths checked; 17 role rows |
| 9 | Local CI (without the secrets job, which needs a commit) | `scripts\ci_local.ps1 -Skip secrets` | 6/6 steps pass, incl. `uv sync --frozen` and pip-audit 2.10.1: "No known vulnerabilities found" |
| 10 | Pre-commit hooks on the staged first commit | `uv run pre-commit run` | gitleaks (staged, redacted) Passed; block private keys Passed; ruff check Passed; ruff format Passed |
| 11 | First commit and its author | `git commit`; `git log --format="%h %an <%ae>"` | `951febc` by `Vamsi Alla <339370878+vamsialladev@users.noreply.github.com>`; the only author email in the history |
| 12 | gitleaks over the full history | `scripts\secrets_scan.ps1` | "1 commits scanned … no leaks found"; script exit 0 |
| 13 | Why the 0-commits check exists | gitleaks v8.30.1 on a fresh `git init` (scratchpad) | "0 commits scanned … no leaks found" with **exit 0**: gitleaks alone would pass having scanned nothing; `secrets_scan.ps1` fails that case (ADR-0007) |
| 14 | Preflight without `.env` | `uv run python -m app.preflight --profile core` | every required name `missing`, no values; `Result: NOT READY`; exit 1 |
| 15 | Leak scanner without `.env` | `scripts\leaks.ps1` | "NOT RUN: no .env file, so no secret value was checked"; exit 3 |
| 16 | `.env` creation on a throwaway copy (not this repo's `.env`) | `scripts\new_env.ps1` in a scratchpad copy, twice; then preflight `--env-file` on it | created with 6 generated values, none printed; second run "already exists: left unchanged", exit 1; preflight `core` **READY**, exit 0; the copy was deleted |
| 17 | `.env` deny rules in Claude Code | owner starts Claude Code in this folder and asks it to read `.env` | Superseded: the owner starts sessions in `C:\projects\project1`, so the rules moved up a level (ADR-0008); see #19–#22 |
| 18 | Owner's own run (reported by the owner, 2026-11-16) | `scripts\leaks.ps1` before and after `scripts\new_env.ps1`; `scripts\preflight.ps1 -Profile core` | leaks: NOT RUN before `.env`; after: "7 secret values against 45 tracked files: 0 leaks" (6 generated values plus `DATABASE_URL`, which carries the password). `new_env.ps1`: 6 values, none printed. Preflight `core`: READY |
| 19 | Project1-wide deny rules written | scratchpad `make_deny.py` → `C:\projects\project1\.claude\settings.json` (new file; `settings.local.json` untouched) | 206 deny rules; not in any repo, not committed |
| 20 | Read tool on a `.env` under project1 | `Read C:\projects\project1\deny-canary\.env` | refused: "File is in a directory that is denied by your permission settings" (the canary was never created: the command creating it was blocked too, so the rule matched on the path alone) |
| 21 | Read tool on a template | `Read points-posting-investigator\.env.example` | refused. Side effect of `.env.*`, waiting on the owner's choice (ADR-0008) |
| 22 | Shell read of a `.env` | `Get-Content C:\projects\project1\deny-canary\.env` | refused: "Permission to use PowerShell with command … has been denied" |
| 23 | GitHub repo created (owner's OK, 2026-11-16) | `gh repo create vamsialladev/points-posting-investigator --public …`; `gh repo edit --add-topic …` | public; description set; homepage `https://vamsialla.com`; 11 topics |
| 24 | Secret scanning and push protection | `gh api -X PATCH repos/vamsialladev/points-posting-investigator` (`security_and_analysis`) | `secret_scanning: enabled`, `secret_scanning_push_protection: enabled` |
