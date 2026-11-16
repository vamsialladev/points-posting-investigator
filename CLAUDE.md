# Project: AI Points-Posting Incident Investigator (portfolio simulation)

Stage 10 of the simulated hotel-group engagement on vamsialla.com, after Stage 9 (loyalty-support-modernization).
It builds the points-posting pipeline behind Stage 9's "missing points" cases, then an alert-triggered, read-only AI
investigator with human-approved recovery. Fictional hotel group (`hg-demo`: Beach Resort, Mountain Lodge), synthetic
data, simulated people.

**This folder is the repository root:** create every file here, run every command from here, and commit only in this
repo. The parent folder's `CLAUDE.md`, `HANDOFF.md` and `PROGRESS.md` belong to the portfolio project and do not apply
here. **Stage 9 (`..\loyalty-support-modernization`) is read-only:** read it, reuse its patterns, never modify it.

- **Source of truth:** `docs/MASTER-SPEC.md`. Read the Part for the current milestone before changing code.
- **Builder:** Claude Code, not Codex (ADR-0001). The spec's Codex steps are an optional exercise for the owner.
- **Release plan:** `docs/implementation-plan.md` (v1 / v2).
- **Site and repo conventions to match:** `docs/continuity.md`.
- **Codex and other agents:** `AGENTS.md` points to these rules and must not contradict them. If it ever disagrees,
  this file and the spec win; fix `AGENTS.md`.

## Standing rules from the owner (2026-11-16, every session)
1. **Scope: a v1 release first.** v1 is the spec milestones listed in `docs/implementation-plan.md`: the investigator,
   the labelled incident set and benchmark, tracing, the outbox and dead-letter replay, and a demo. Everything else is
   tiered as v2 "what's next". Nothing from the spec is dropped; every requirement has a release in
   `docs/requirements-matrix.md`. The v1 plan was shown to the owner and approved before coding (2026-11-16).
2. **Plan before code on design-heavy milestones:** **2, 3, 6, 7, 9, 10**. Show the plan and wait for the owner's
   approval. M3 is on the list because it holds the benchmark pre-registration. Plan again whenever a bug survives two
   fix attempts.
3. **Honesty:**
   - Every number traces to a stored result file.
   - Synthetic data and simulated people are labelled.
   - Mock results are never presented as live.
   - Hypotheses, thresholds and the incident catalog are pre-registered (committed in M3, before any arm or
     investigator code; `tests/test_preregistration.py`).
   - Report where AI did not help.
   - Missing credentials produce NOT RUN, never a pass.
4. **Secrets:**
   - Never ask the owner to paste secrets into chat, and never show them in output.
   - Use `.env` and dashboard or secret-manager values only.
   - `python -m app.preflight --profile <name>` reports set / missing / invalid format without printing values.
   - After any credential rotation, prove the old credential fails.
   - Never put a secret in a command line or prompt text.
5. **Money:** nothing that costs money, deploys publicly or uses the owner's accounts without the owner's explicit OK
   and a stated cap. Mock AI by default.
6. **Git:** branches, PRs, and merge with a merge commit only when CI is green (standing permission).
   - Author email: `339370878+vamsialladev@users.noreply.github.com`, set repo-local. Check `git log --format=%ae`
     before any push.
   - **Ask before creating the GitHub repo** (it will be public).
   - Until the repo exists, milestones go on local branches merged into `main` with `--no-ff`.
7. **Tests:**
   - Real-database (and real-Kafka) tests wherever behaviour depends on them.
   - Never weaken or delete a test to make it pass.
   - **A check that scans or tests nothing must fail.** That covers `REQUIRE_MARKERS` in `tests/required_markers.py`,
     `app.env_leaks` NOT RUN (exit 3), `scripts\secrets_scan.ps1` refusing 0 commits, and pytest's "no tests
     collected".
8. **Purpose lenses** (same as Stage 9, `docs/project-purpose.md`), kept proportionate, plus
   `docs/role-coverage-map.md` (roles exercised, with evidence only).
9. **Portfolio house style at the end:**
   - a stage card with three verified metrics
   - a case study
   - a narrated demo video with a generated voice, labelled "AI-narrated" and not imitating the owner (ADR-0004)
   - a README consistent with the owner's other repos

   Website changes only as PRs the owner approves.
10. **Keep `docs/session-handoff.md` current**, and end each milestone with a 3-line summary: what changed, and what the
    owner must do.

## Every session
1. Read `docs/implementation-status.md` and `docs/session-handoff.md`.
2. Run `scripts\test.ps1` (or `make test`) to see the current state before editing.
3. Work only on the milestone or task named in the prompt. Tell the owner if it is design-heavy (rule 2).
4. After changes: run the relevant tests, review `git diff`, and update `docs/requirements-matrix.md`,
   `docs/implementation-status.md`, `docs/verification-log.md` and `docs/session-handoff.md`.
5. Commit with a Conventional Commits message when checks pass. **Never push with failing checks**; merge only when CI
   is green.
6. End each milestone with the spec's Part N teaching notes: what changed, why, how to verify, failure modes, one
   exercise. Then the 3-line summary (rule 10).

## Engineering rules
- Spec Part 0.3 rules are non-negotiable: no fabricated results, URLs, users, incidents, approvals, savings or tool
  usage.
- **The AI only reads and recommends.** Its tools are typed and read-only, with no shell, SQL, network or write tools.
- **Deterministic Python only:** alert rules, replay eligibility, idempotency, authorization, approval and recovery
  execution.
- **Recovery:** a person approves every recovery, and that person is not the requester. The approval is bound to the
  exact message set.
- **No double credit:** the ledger refuses a second credit for one idempotency key, at the database level.
- **No exactly-once claims.**
- Verify library and protocol APIs in current official docs; pin versions with uv (`uv.lock` is committed).
- Record which tool did each piece of work: the commit trailer and `docs/verification-log.md`.
- Every piece of work maps to a requirement ID in `docs/requirements-matrix.md`. New ideas go to `docs/backlog.md`
  and are not built until the owner approves them.
- Do not start a higher scope tier while a lower tier's verified checks fail (spec 0.5).

## Secrets
- Never open, print or `cat` `.env`. Check readiness only with `scripts\preflight.ps1 -Profile <name>`.
- `.claude/settings.json` denies reading `.env` files; respect it.
- `scripts\new_env.ps1` creates `.env` with random local values and prints none of them.
- Never write a real value into a committed file, log, screenshot, fixture or prompt.

## Portfolio writing
- Plain English and short sentences.
- Specific numbers, with counts and denominators.
- Honest about limits.
- Label everything as an independent portfolio simulation with synthetic data.
- The owner's current title is Senior Software Engineer. "Forward Deployed Engineer" appears only as a role being
  sought.

## Windows notes
- Python 3.12 via `uv`. `make` is not installed on the owner's machine, so every make target has a `scripts\*.ps1`
  twin.
- gitleaks, Trivy and Terraform run from pinned Docker images; nothing to install.
- Two GitHub accounts are signed in to `gh`. When pushing, use
  `git -c credential.helper= -c "credential.helper=!gh auth git-credential" push` so the vamsialladev credential is
  used.
- Never use shell heredocs containing backslashes on Windows; write files with the editor tools instead.
