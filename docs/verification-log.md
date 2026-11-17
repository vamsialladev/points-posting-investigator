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
| 25 | Owner's three probes, same session as the rules were written (2026-11-16) | owner asked: "Read deny-canary\.env"; "Run Get-Content deny-canary\.env"; "Run cat deny-canary/.env in Bash" | all three refused: Read "denied by your permission settings"; PowerShell and Bash "Permission … has been denied". No canary value shown (no canary file existed) |
| 26 | The same three probes, **fresh session** started in `C:\projects\project1` (2026-11-17), before any change | same three, run by Claude Code | all three refused, same messages: the project1 rules load in a new session (closes #17) |
| 27 | The gap, before the change (same fresh session) | `Read C:\projects\project1\deny-canary\prod.env` | **not refused**: it reached the filesystem ("File does not exist"). File rules covered `.env` and `.env.*`, not `*.env` |
| 28 | Change written (owner's request, ADR-0009) | scratchpad `update_deny.py` on `C:\projects\project1\.claude\settings.json` (backup kept in the scratchpad); this repo's `.claude/settings.json` edited | project1: 206 → 368 deny rules; the 6 broad `.env.*` file rules removed, nothing else; `*.env` and named variants added. Outside every repo, not committed |
| 29 | After the change: `*.env` and variants refused | `Read deny-canary\prod.env`; `Read C:\projects\project1\deny-canary.env`; `Read points-posting-investigator\.env.local`; `Write deny-canary\prod.env` (fake content) | all four refused: "denied by your permission settings"; nothing was written |
| 30 | After the change: the template is readable | `Read points-posting-investigator\.env.example` | read normally (it was refused before, #21) |
| 31 | The project1 file, checked with the tested matcher | `glob_matches` from `tests/test_secrets_hygiene.py` over the live file | 228 file rules, 140 shell rules; **0** rules match `.env.example`; `.env`, `prod.env`, `deny-canary.env`, `.env.local`, `.env.production` and `.env.bak` all matched |
| 32 | New tests | `uv run pytest tests/test_env_template.py tests/test_secrets_hygiene.py` | pass: the detector flags 10 planted fakes, leaves 7 safe defaults alone, never prints a value; the real `.env.example` (≥30 names) has no problem; the glob matcher is right on 7 known answers. Full `scripts\test.ps1`: ruff, format and mypy clean; **129 passed**; coverage 98.96% |
| 33 | No whole credential shape in the new test file | `Select-String` for `sk-ant-…`, `AKIA…`, `ghp_…`, `xoxb-`, Slack webhook in `tests/test_env_template.py` | none: every planted fake is split with `+` |
