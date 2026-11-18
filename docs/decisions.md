# Decisions (ADRs)

Each ADR uses the same headings as Stage 9: Context, Options considered, Decision, Tradeoff, Result, What would change
this decision. Updates are added as dated bullets; nothing is rewritten.

## ADR-0001: Claude Code builds Stage 10; the spec's Codex steps are an optional exercise
- **Context:** `docs/MASTER-SPEC.md` names Codex as the builder: "How to use (Codex)", the Appendix A session kit and
  `AGENTS.md`. The owner is using Claude Code instead (2026-11-16).
- **Options considered:**
  1. Follow the spec literally with Codex.
  2. Claude Code builds, and every Codex step is dropped.
  3. Claude Code builds, and the Codex kit is kept as an optional exercise the owner can run.
- **Decision:** option 3.
  - `CLAUDE.md` holds the rules.
  - `AGENTS.md` (spec Appendix A, adapted) points to `CLAUDE.md`, so a Codex session follows the same standard.
  - Any Codex run is logged in `docs/verification-log.md`: task, time to a verified result, defects found, tests
    passed.
- **Tradeoff:** two guidance files must stay consistent. `tests/test_repo_guidance.py` checks that `AGENTS.md` names
  `CLAUDE.md`, the spec, the read-only AI rule and the noreply address.
- **Result:** the commit trailers and the verification log record which tool did each piece of work.
- **What would change this decision:** the owner choosing Codex for a milestone. That milestone's work would then be
  recorded as Codex's.

## ADR-0002: Release v1 first; tier the rest of the spec as v2, dropping nothing
- **Context:** standing rule 1. The spec has 17 milestones in 4 tiers. The owner asked for a v1 release (the
  investigator, the labelled incident set and benchmark, tracing, the outbox and dead-letter replay, a demo), with the
  rest marked as v2.
- **Options considered:**
  1. Build all 17 milestones in order before any release.
  2. v1 = spec Tier 1 (M1–9) only, with no demo.
  3. v1 = Tier 1, plus a minimal automation slice (needed for the alert → incident → investigation demo flow), plus
     the CI part of M13, the draft threat model of M12, and the README, video and case study of M16, plus M17 on the
     v1 scope.
- **Decision:** option 3 (`docs/implementation-plan.md`). Every spec requirement has a row with `Release: v1|v2` in
  `docs/requirements-matrix.md`.
- **Change made during the owner's review (2026-11-16):** the first draft put the hypotheses and thresholds in M9,
  after arms A and B (M5). The owner's checklist asked for them to be committed **before any arm or investigator
  code**, as in Stage 9. They now sit in M3, with the failure catalog and a benchmark protocol (BENCH-07).
  `tests/test_preregistration.py` will check the commit order.
- **Tradeoff:**
  - v1 has no n8n, no ticketing mocks, no Stage 9 write-back, no cloud and no drills. The case study must say so.
  - The minimal automation slice is built in M8, and M10 extends it, so its design must leave room for the circuit
    breaker and the notifications.
- **Result:** v1 can ship and be shown honestly. v2 has a written list.
- **What would change this decision:** the owner moving an item between releases; this ADR gets an update.

## ADR-0003: Reuse Stage 9's patterns instead of reinventing them
- **Context:** Stage 9 already solved preflight, secrets hygiene, local CI, write-path safety, the benchmark method and
  the purpose lenses (`docs/continuity.md` §6).
- **Options considered:**
  1. Write fresh versions.
  2. Import Stage 9 as a library.
  3. Port the patterns, with attribution and adaptations recorded.
- **Decision:** option 3. Stage 9 is an application, not a library, and its domain differs (loyalty cases vs posting
  incidents). A dependency would couple the two releases. What M1 ported:
  - `app/preflight.py` and its tests
  - `app/env_leaks.py`, with the rule-7 fix in ADR-0007
  - `.claude/settings.json` deny rules
  - `.gitignore` / `.dockerignore` / `.gitattributes`
  - `.pre-commit-config.yaml`
  - `scripts\test.ps1` and `scripts\ci_local.ps1`
  - the tracking-file formats and the purpose lenses

  Later milestones port Stage 9's write-path pattern (RFC-0001: HMAC binding, stable keys, reconciliation), its
  freeze and pre-registration tests, and its scrubbing trace exporter.
- **Tradeoff:** a fix in one copy doesn't reach the other. A pattern used by three or more stages becomes a candidate
  for `hotel-ai-platform` (backlog).
- **Result:** M1's setup reused these files directly, and Stage 9's known gaps were fixed on the way in (ADR-0007).
- **What would change this decision:** a third stage needing the same code; then extract it into `hotel-ai-platform`.

## ADR-0004: Demo narration is a generated voice labelled "AI-narrated", plus an own-voice script
- **Context:** spec Part O asks for a first-person narration script "I record myself" and says never to use a
  synthetic voice imitating the owner. The owner's standing rule 9 asks for a narrated video with the generated voice
  labelled. The portfolio rules (`CLAUDE.md` §18 at the portfolio level, changed 2026-10-25) allow AI narration only if
  it sounds natural and is labelled.
- **Options considered:**
  1. Owner's voice only.
  2. Generated voice only.
  3. A generated, non-imitating voice, labelled, plus the owner's first-person script, captions and a silent
     captioned version.
- **Decision:** option 3. The voice is the video kit's Kokoro voice, not a clone. Labels use the site's exact wording
  ("AI-narrated"; "Narrated with a generated voice; captions included."). `docs/VIDEO_SCRIPT.md` is written so the
  owner's recording can replace it.
- **Tradeoff:** a generated voice is less personal.
- **Result:** planned for M16.
- **What would change this decision:** the owner recording their own voice, which then replaces the generated one.

## ADR-0005: Python 3.12 for every service; Java/Spring Boot stays in the backlog
- **Context:** spec 0.4.
- **Options considered:**
  1. A Java posting service to show the owner's Java background.
  2. Python everywhere.
- **Decision:** Python 3.12 everywhere (`requires-python = ">=3.12,<3.13"`). A Java posting service is a backlog
  idea.
- **Tradeoff:** the portfolio's Java and distributed-systems story isn't shown in code here.
- **Result:** one toolchain (uv, ruff, mypy, pytest) for every service.
- **What would change this decision:** the owner approving the backlog item.

## ADR-0006: Preflight profiles follow Stage 10's deployment shapes
- **Context:** Stage 9's profiles (portfolio, live-model, staging, approved…) fit a FastAPI app with an OIDC option.
  Stage 10 has a different set of moving parts: Kafka, observability, n8n, the Stage 9 adapter and AWS.
- **Options considered:**
  1. Keep Stage 9's profile names.
  2. One profile per Compose profile and per optional integration.
- **Decision:** option 2: `core`, `observability`, `automation`, `live-ai`, `stage9-adapter`, `deploy`. Overlays accept
  `APP_PROFILE=core`. The checks:
  - `live-ai` is never ready without both budget caps set.
  - Every profile refuses long-lived AWS keys (`AWS_ACCESS_KEY_ID` and friends) by name: SSO only.
  - `deploy` refuses local hosts, debug logging, and default, test or short secrets.
  - A live provider without `FEATURE_LIVE_AI=true`, or the reverse, is a problem, so the two can't silently disagree.
  - `LOG_LEVEL` is added to Appendix B's names.
- **Tradeoff:** six profiles to keep tested. `tests/test_preflight.py` covers each.
- **Result:** `scripts\preflight.ps1 -Profile core` reports set / missing per name and never a value
  (`tests/test_preflight.py::test_output_never_contains_values`, over every profile, as text and JSON).
- **What would change this decision:** a new integration; it gets its own profile.

## ADR-0007: A check that scans or tests nothing fails
- **Context:** standing rule 7. Stage 9's `app/env_leaks.py` exits 0 when there is no `.env` (its own test,
  `test_cli_without_env_file`), so it passes having checked nothing. Stage 9's `REQUIRE_BROWSER` guard covers only
  browser tests.
- **Options considered:**
  1. Keep Stage 9's behaviour.
  2. Make each scanner fail on empty input, and generalise the skip guard to any marker.
- **Decision:** option 2.
  - `app/env_leaks.py` returns **NOT RUN (exit 3)** when there's no `.env`, no secret values in it, or no tracked
    files.
  - `scripts\secrets_scan.ps1` fails unless gitleaks reports scanning at least one commit.
  - `tests/required_markers.py`: with `REQUIRE_MARKERS=postgres,kafka,browser`, a skipped test with a required marker
    is a failure, and so is a session that selected none.
  - pytest's "no tests collected" (exit 5) already fails `scripts\test.ps1`.
- **Tradeoff:** a laptop without `.env` sees `scripts\leaks.ps1` fail. That is the intended signal (NOT RUN, with the
  reason), and CI doesn't run it (CI has no `.env`; gitleaks covers CI).
- **Result:** the guard's own test caught a bug in its first version. Counting at `pytest_collection_modifyitems`
  happened before `-m` deselection, so `-m "not postgres"` stayed green. The count moved to
  `pytest_collection_finish` (`tests/test_required_markers.py::test_deselecting_every_required_test_fails_too`).
- **Update (2026-11-16):** gitleaks v8.30.1 on a repository with no commits prints "0 commits scanned … no leaks
  found" and **exits 0** (verification log, M1 #13). gitleaks alone would report a pass that scanned nothing; the
  script's count check is what fails it.
- **What would change this decision:** nothing foreseen. It is a standing rule.

## ADR-0008: Secret deny rules also live at the project1 level, where sessions start
- **Context:** the owner starts Claude Code sessions in `C:\projects\project1`, not inside this repo (2026-11-16).
  This repo's `.claude/settings.json` may then not apply, so a session could read `.env` here or in any other project.
- **Options considered:**
  1. Keep the rules only in each repo, and ask the owner to start sessions inside the repo.
  2. Put them in the user-level settings (`~/.claude/settings.json`), so they apply everywhere on the machine.
  3. Add equivalent rules to `C:\projects\project1\.claude\settings.json`, covering every project under project1.
- **Decision:** option 3, with the owner's permission.
  - The file was created (none existed). The existing `settings.local.json` (allow rules only) was left untouched.
  - It holds 206 deny rules:
    - `Read`, `Edit` and `Write` of `.env`, `.env.*`, `secrets/**`, `.secrets/**`, `*.pem`, `*.key`, `*.p12`,
      `*.pfx`, `id_rsa*`, `id_ed25519*` and `secrets.toml`, at the root and at any depth (`./**/`)
    - shell reads of the same names through `cat`, `type`, `Get-Content`, `gc`, `more`, `less`, `head`, `tail`,
      `Select-String` and `findstr`, in both Bash and PowerShell forms
  - The file sits outside every repo and is not committed (project1 is not a Git repository). This repo's own
    `.claude/settings.json` stays, for sessions started here.
- **Tradeoff:**
  - **`.env.*` also matches `.env.example`**, so Claude Code can no longer read or edit any project's template under
    project1 (probe 21 below). Deny rules can't be excepted; keeping the template readable means replacing `.env.*`
    with named variants (`.env.local`, `.env.bak`, `.env.production`…), at the cost of missing an unforeseen name.
    Waiting on the owner's choice.
  - Shell-pattern rules match command text. A reader not on the list, or a script that opens the file itself (for
    example Python), isn't blocked. The rules are a guard against mistakes, not a sandbox.
- **Result:** checked from this session (started in `C:\projects\project1`) right after the file was written:
  - `Read` of `C:\projects\project1\deny-canary\.env`: refused ("denied by your permission settings")
  - `Get-Content` of the same path: refused
  - `Read` of this repo's `.env.example`: refused

  The canary file was never created: the command that would have created it was blocked too. So the rules matched on
  the path alone, and no real `.env` was ever opened. Verification log, M1 #19–#22.
- **Update (2026-11-17):** the `.env.example` tradeoff is resolved by ADR-0009: named variants replace `.env.*`, and
  `*.env` is added.
- **What would change this decision:** the owner preferring machine-wide rules (option 2), or starting sessions inside
  each repo.

## ADR-0009: Block every file ending in `.env`; keep `.env.example` readable, and test that it stays safe
- **Context:** a fresh session started in `C:\projects\project1` (2026-11-17) refused all three probes of a `.env`.
  But a Read of `deny-canary\prod.env` **was not** refused: it reached the filesystem ("File does not exist"). The
  file rules matched `.env` and `.env.*` only, so `prod.env` or `deny-canary.env` was open to Read, Edit and Write.
  Only the shell rules (`*.env`) covered them. Separately, `.env.*` also blocked the safe `.env.example` everywhere
  (ADR-0008). The owner asked to close the first gap, keep the template readable, and test that the template never
  holds a real-looking value.
- **Options considered:**
  1. Keep `.env.*` and add `*.env`: closes the gap, but every template stays unreadable.
  2. An exclusion glob such as `.env.[!e]*`: unclear in Claude Code's matcher, and it also opens `.env.enc` or
     `.env.edge`.
  3. Named variants instead of `.env.*`, plus `*.env`, plus a test that the template is safe to read.
- **Decision:** option 3.
  - **project1** (`C:\projects\project1\.claude\settings.json`, outside every repo): Read, Edit and Write of `*.env`
    and of `.env.local/.development/.dev/.staging/.stage/.production/.prod/.test/.testing/.ci/.live/.preview/.docker/
    .secret/.secrets/.bak/.backup/.old/.orig/.save/.copy/.tmp`, plus `.env.*.local`, `.env*.bak`, `.env*.backup`,
    `.env*.old` and `.env*~`, at the root and any depth. The six broad `.env.*` file rules were removed; nothing else
    was. 206 → 368 rules: 228 file rules, 140 shell rules.
  - **Shell reads keep the broad `*.env.*`**, so `Get-Content .env.example` is still refused. The Read tool is how
    templates are read and edited, and a shell rule that is too broad fails safe.
  - **This repo's** `.claude/settings.json` gets `*.env` for Read, Edit and Write. It never had `.env.*`.
  - **New tests:**
    - `tests/test_env_template.py`: `.env.example` holds no real-looking value. Two layers:
      - secret shapes anywhere in the file, comments included: Anthropic, GitHub, AWS and Slack credentials, private
        keys, a password written into a URL, JWTs
      - any value for a secret variable, or a random-looking credential

      Its detector is tested first on 10 planted fakes and 7 safe defaults. The fakes are split with `+`, so no
      scanner sees a whole credential in the source.
    - `tests/test_secrets_hygiene.py`: the repo's rules cover `*.env` for all three tools, and no file rule matches
      `.env.example` (checked with a glob matcher that is itself tested on known answers).
- **Tradeoff:**
  - A secret file named with an unlisted variant (say `.env.qa`) is open to the Read tool. It is still refused to the
    shell readers.
  - Files ending in `.env` that hold no secret are blocked too. Stage 9's `config/environments/*.env` is an example,
    but Stage 9 is read-only here anyway.
- **Result:** verification log, M1 #25–#33. Before the change, `prod.env` was not refused; after it, `prod.env`,
  `deny-canary.env` and `.env.local` were refused to Read, and Write of `prod.env` was refused. `.env.example` reads
  normally. The project1 file was checked with the same tested matcher: 228 file rules, none matches `.env.example`,
  and every listed secret name is matched.
- **What would change this decision:** a new env-file naming habit (add the variant), or Claude Code adding
  exception rules (go back to `.env.*` with an exception for `.env.example`).
- **Update (2026-11-17, owner's request):** the unlisted-variant gap is now detected. Two tests in
  `tests/test_secrets_hygiene.py` walk the repo (tracked, untracked and ignored files; names only, nothing opened):
  - one fails if any `.env`, `.env.*` or `*.env` file other than `.env.example` has no matching Read rule in this
    repo's settings
  - the other runs the same check against the project1 rules, locally (CI has no project1 file, so it skips there)

  A third test plants empty files in a temporary folder to prove the check fails on an uncovered `.env.qa`. The gap
  is caught when such a file exists and the tests run, not the moment the file is created.

## ADR-0010: Adopt RFC-0001 (pipeline, outbox, idempotent ledger) as approved
- **Context:** Milestone 2 is design-heavy (standing rule 2). `docs/rfcs/RFC-0001-pipeline-outbox-ledger.md` set out
  twelve choices, D1 to D12, with an approval checklist. The owner approved it as written on 2026-11-17.
- **Options considered:** the alternatives in each D of the RFC (Redpanda; `aiokafka`; Confluent Schema Registry or
  Apicurio; JSON Schema; outbox-first crediting; several relays; testcontainers).
- **Decision:** the RFC's recommendations, D1 to D12. Pinned on the build day:
  - images: `apache/kafka:4.4.0`, `ghcr.io/aiven-open/karapace:6.2.4`, `postgres:16.15-alpine`,
    `python:3.12.16-slim`, `ghcr.io/astral-sh/uv:0.13.5`
  - packages: `confluent-kafka` 2.16.1, `fastapi` 0.162.7, `sqlalchemy` 2.1.9, `psycopg` 3.3.9, `alembic` 1.20.1
  - actions: pinned to full commit SHAs
- **Tradeoff:** the RFC's main risk, Karapace against `confluent-kafka`'s registry client, could only be checked by
  building. And the RFC said Karapace's image was lighter than Confluent's, which I hadn't checked: the Karapace image is
  1.72 GB. The choice stands on the licence and the matching API, not on size.
- **Result:** delivered in three PRs. PR-A (the stack, the ledger mock, CI): an Avro event round-trips through Kafka
  and Karapace unchanged, and the registry enforces `BACKWARD_TRANSITIVE` (verification log, M2). Differences while
  building are in the RFC's "Differences while building" and in ADR-0011 and ADR-0012.
- **What would change this decision:** the RFC's own list (Kafka can't run on the owner's machine; the owner prefers
  Confluent's registry; the relay becomes a bottleneck).

## ADR-0011: Each runtime database role has its own password; owner roles can't log in
- **Context:** RFC-0001 D9 gives each database an owner role and a runtime role, but didn't say how a service gets
  its password. While building, the first idea was to derive each password from the Postgres superuser password (an
  HMAC, as Stage 9's demo launcher does). That would give every service the superuser password.
- **Options considered:**
  1. Derive role passwords from the superuser password: no new settings, but every service could log in as superuser.
  2. A separate password per runtime role in `.env` (`LEDGER_DB_PASSWORD`, `POSTING_DB_PASSWORD`), and owner roles
     with NOLOGIN: migrations run as the superuser under `SET ROLE <owner>`.
  3. One shared runtime password.
- **Decision:** option 2. Services get only their runtime role's password. The bootstrap revokes and re-grants every
  runtime right from one list (`app.db.roles.GRANTS`), so the rights are always exactly the listed ones.
  `scripts\new_env.ps1 -AddMissing` adds the two new values to an existing `.env` without touching anything else.
- **Tradeoff:** two more local secrets, and the owner's existing `.env` needed them. Claude Code ran `-AddMissing` on
  it after testing it on a throwaway copy; no value was printed.
- **Result:** tested on real Postgres, as the real roles:
  - the ledger's runtime role can't UPDATE, DELETE, TRUNCATE or DROP a credit
  - owner roles can't log in
  - a runtime role can't reach the other database
  - a rotated password locks out the old one

  See the verification log, M2.
- **What would change this decision:** a secret manager (v2 deployment) issuing short-lived database credentials.

## ADR-0012: `localhost` means 127.0.0.1 for database connections, with a 10-second connect timeout
- **Context:** the first integration run hung for 10 minutes. A stack dump showed libpq waiting in the connection
  setup. On this Windows machine `localhost` resolves to `::1` first. Docker Desktop accepted that connection and
  never answered, and libpq had no timeout.
- **Options considered:**
  1. Change `.env.example` to `127.0.0.1`: fixes new setups, not the owner's existing `.env`.
  2. Bind the stack to `::1` as well.
  3. Map `localhost` to `127.0.0.1` in one function (`app.db.roles.loopback`), and set `connect_timeout=10` on every
     connection.
- **Decision:** option 3. The stack binds 127.0.0.1 only, so the IPv4 address is the one that works. The timeout means
  a connection fails in 10 s instead of hanging.
- **Tradeoff:** a host name is rewritten in code. That is visible, tested (`tests/test_db_offline.py`), and limited to
  `localhost`.
- **Result:** the Postgres tests went from a 10-minute hang to 26 passing in 9 s. A probe recorded the cause:
  `127.0.0.1` connected at once, while `localhost` took 5.0 s with a 5 s timeout.
- **What would change this decision:** the stack binding IPv6 as well, or a deployment where `localhost` isn't the
  Docker host.

## ADR-0013: `main` requires all five CI checks before anything merges, admins included
- **Context:** standing rule 6 is "merge only when CI is green". On 2026-11-18 I enabled GitHub auto-merge on PR #2,
  expecting it to wait for CI. `main` had no required checks, so auto-merge had nothing to wait for. PR #2 merged at
  once, **before its CI ran**, and its CI then **failed**: a flaky assertion in the ledger race test (verification
  log, M2 #19–#21). The rule had relied on me checking by hand, and the one time I relied on a tool, the tool didn't
  check.
- **Options considered:**
  1. Keep merging by hand after reading `gh pr checks`, and never use auto-merge.
  2. Branch protection on `main` that requires the five CI jobs and an up-to-date branch, for admins too, with no force
     pushes and no deletion.
  3. A repository ruleset with the same rules.
- **Decision:** option 2, with the owner's OK (2026-11-18). The required checks:
  - Lint, types, offline tests
  - Real Kafka, Karapace and Postgres
  - Migrations round trip and drift check
  - Secret scan of the full history
  - Known vulnerabilities in the locked dependencies
- **Tradeoff:** a new or renamed CI job must be added to the protection, or a renamed one will block every merge. The
  owner can't merge around a red check either: that's the point, and it is reversible in the repository settings.
- **Result:** proven on the PR that fixed the flaky test (verification log, M2 #23). A plain merge before the checks
  finished was refused, and auto-merge then waited for them.
- **What would change this decision:** a second contributor (then add required reviews), or moving to rulesets for
  several branches.
