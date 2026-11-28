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
- **Result:** shown on PR #4, the fix for the flaky test (verification log, M2 #24):
  - while its checks ran, GitHub reported `mergeStateStatus: BLOCKED`
  - auto-merge, enabled with `--merge`, stayed armed and waited

  No merge was attempted before the checks finished, not even as a test: the auto-mode classifier refused that
  command, rightly.
- **What would change this decision:** a second contributor (then add required reviews), or moving to rulesets for
  several branches.

## ADR-0014: Outbox relay: several relays claim each member's oldest open row; at-least-once delivery
- **Context:** M2's second PR publishes committed outbox rows to Kafka. It must stay correct when a relay crashes,
  retries or runs twice, keep one member's events in order, survive a Kafka outage, and dead-letter poison without
  blocking anyone else. The owner approved the plan on 2026-11-22, including four changes to RFC-0001:
  1. The ledger stays a separate system of record. What shares one Postgres transaction is the posting row and its
     outbox row (PR-B2), not the ledger write.
  2. Several relays, replacing D6's single active relay.
  3. A separate `posting_relay` database role.
  4. Consumer-side retry topics stay in PR-C.
- **Options considered:**
  1. One active relay behind an advisory lock (RFC-0001 D6). Order is trivially kept, but there's no parallelism,
     and failover waits on the lock.
  2. Several relays with plain `FOR UPDATE SKIP LOCKED`. Rows are never claimed twice, but two relays can publish the
     same member's rows 1 and 2 in the wrong order.
  3. Several relays, each holding a lease on a hash bucket of members. Order is kept, but bucket leases, rebalancing
     and skew add moving parts.
  4. Several relays with `FOR UPDATE SKIP LOCKED`, where only the **oldest open row of each member** is claimable
     (`NOT EXISTS` an older `pending`/`in_flight` row with the same key), with a lease on each claim.
- **Decision:** option 4, with these parts:
  - **Delivery state on the outbox row** (migration 0002):
    - `status` (`pending`, `in_flight`, `published`, `dead`)
    - `next_attempt_at`, `claimed_by`, `lease_until`, `dead_at`
    - `trace_context`
    - check constraints that tie each status to its timestamp
  - **Marking:** only while the relay still holds the claim (`claimed_by` and `in_flight`).
  - **At least once:** a crash after publishing and before marking means another relay publishes the row again
    after the lease. `points.posted` readers dedupe on `event_id`, which is fixed when the row is written. Nothing
    that reads `points.posted` writes to the ledger.
  - **Failure classes:**
    - Transient (broker unreachable, delivery timeout, full queue): retried after a short jittered delay. Never
      counted, so an outage doesn't dead-letter good messages. While the broker is unreachable the relay doesn't
      claim at all.
    - Permanent (serialization, message too large, unknown): exponential backoff, then `dead` at `max_attempts` (5).
      A dead row unblocks its member's later rows. Dead rows are never replayed automatically; replay is M7, with
      approval.
  - **Trace context:** W3C `traceparent`/`tracestate`, through a small helper until M4's OpenTelemetry.
  - **Metrics on `/metrics`:**
    - `outbox_oldest_unpublished_age_seconds` (lag)
    - `outbox_unpublished_rows`
    - `outbox_dead_rows`
    - `outbox_publish_failures_total{error_class}`
    - `outbox_published_total`
    - `outbox_dead_lettered_total`

    Alert rules are code in M4 (OBS-05).
  - **The `posting_relay` role:**
    - can read the outbox
    - can update only the delivery columns
    - can't insert, delete or rewrite a message
    - can't read `posting`

    `posting_app` no longer updates the outbox at all.
- **Tradeoff:**
  - **One member has one message in flight at a time,** so per-member throughput is one message per cycle. That's
    fine for loyalty postings, which are sparse per member, and a real limit for a hot key.
  - **The claim's `NOT EXISTS`** reads the member's open rows. An index (`outbox_open_by_key_idx`) serves it.
  - **Stats scan the outbox** each cycle. That's fine at demo scale; a real one needs a retention job.
  - **Transient retries use a fixed short delay,** not a growing one. The broker check is what stops the relay
    hammering during an outage.
  - **One more local secret** (`RELAY_DB_PASSWORD`).
- **Result:** verification log, M2 PR-B1. The tests run against real Postgres and Kafka. The crash and concurrency
  tests were each run 10 times (`docs/evidence/m2-pr-b1-repeat-runs-first.md`, `m2-pr-b1-repeat-runs-outage.md`).
  Found while building: Kafka advertised `localhost`, so every new client spent 2 s on IPv6 first. It now advertises
  `127.0.0.1` (same cause as ADR-0012).
- **What would change this decision:** a hot member needing more than one message in flight (then partition-scoped
  leases, option 3), or a broker-side transactional producer if the outbox moved into Kafka itself.

## ADR-0015: Posting service: one transaction for posting + outbox, offset after commit, the stay as the ledger key
- **Context:** M2 PR-B2a builds the posting service. It must never post an event twice, whatever repeats, races or
  crashes. Either both rows (posting and outbox) are written or neither, and an offset must never be committed for
  work that didn't commit. The ledger is a separate system of record with its own database (spec B1.3; approved
  2026-11-22), so it can't share a Postgres transaction with the posting service. The owner approved the B2 plan on
  2026-11-23, with four changes to RFC-0001.
- **Options considered:**
  1. **Transaction boundary:**
     - (a) A distributed transaction across the ledger and the posting database. Not available: the ledger is an
       HTTP service.
     - (b) Write posting + outbox first, then credit from a worker. That adds a second outbox (RFC-0001 D5).
     - (c) Credit the ledger idempotently, then one transaction for posting + outbox.
  2. **Offsets:**
     - (a) Auto-commit. It can commit an offset before the database commits, which loses the event on a crash.
     - (b) Commit before processing: at most once.
     - (c) Commit synchronously, after the database commit: at least once.
  3. **The ledger key:**
     - (a) `event_id` (the RFC's D5)
     - (b) the business key `stay_id:revision`
- **Decision:** 1(c), 2(c), 3(b).
  - **The single transaction:**
    - `INSERT posting … ON CONFLICT DO NOTHING RETURNING`
    - only if a row came back, `INSERT outbox` (with the trace context)
    - a failure anywhere rolls both back
  - **Offsets:**
    - auto-commit and auto offset store are off
    - after the transaction, the consumer commits exactly that message synchronously
    - on a database failure, a dead-letter delivery failure, or (B2a only) a transient ledger failure, it commits
      nothing, seeks back to the same message, and retries after a growing, jittered wait
  - **Idempotency:**
    - **event_id:** the posting row's primary key, and the consumer's first check
    - **Ledger key `stay_id:revision`:** one credit per stay revision, whatever event ID it arrives under
    - **The backstop:** `UNIQUE(stay_id, revision)` on the posting row
  - **Dead letters:** an event that can never post goes to the DLQ topic, with its original bytes and RFC-0001 D8's
    headers, and only then is its offset committed. That covers an event that is undecodable, has an unknown schema
    version, has a bad field, is a correction (until PR-C), or gets a ledger 409 or other 4xx (until B2b counts
    attempts).
  - **Trace context:**
    - the producer starts a W3C trace
    - the posting service stores a child span on the outbox row
    - the relay (ADR-0014) sends a child of that in the `points.posted` headers
- **Tradeoff:**
  - **The ledger is credited before the transaction,** so a crash in between leaves a credit with no posting row
    until redelivery. Redelivery gets the same entry back (the key), then writes the rows. A credit without a
    posting is the one state the ledger can be in temporarily; it never has two credits.
  - **Seeking back blocks that partition** while the database (or, in B2a, the ledger) is down. Every member on the
    partition waits. B2b parks ledger failures so only the affected member waits.
  - **The business key means a genuinely new stay must have a new stay ID or revision.** That's the business rule
    anyway.
- **Result:** verification log, M2 PR-B2a; repeat runs in `docs/evidence/m2-pr-b2a-repeat-runs.md`. Building found
  one test-data mistake: the same stay ID for two members. The service rightly refused the second credit, and the
  test was fixed.
- **What would change this decision:** a ledger that can join a transaction (unlikely for a system of record), or
  corrections (PR-C) needing their own key rule (`stay_id:revision` already separates revisions).

## ADR-0016: Retries park events in Postgres, oldest per member first; no retry topics
- **Context:** in B2a, a transient ledger failure blocked its partition, because the consumer sought back to the same
  message. A permanent refusal was dead-lettered at the first attempt. The owner asked for:
  - retries with backoff, then dead-lettering after max attempts, without blocking the partition
  - per-member order held under retries

  RFC-0001 D8 planned retry topics. They don't keep order: while event 1 waits in a retry topic, event 2 of the same
  member is processed. The owner approved the B2b plan on 2026-11-26.
- **Options considered:**
  1. Retry topics (D8). The partition isn't blocked, but per-member order is lost.
  2. Seek back in place (B2a). Order is kept, but the whole partition is blocked.
  3. Retry topics plus a "member is parked" marker that forces later events into the retry topic too. Order is
     kept, but the marker and the topics have to agree across two systems.
  4. A Postgres parking table:
     - a failed event is parked
     - later events of a member with open parked events are parked behind it
     - a retry worker claims only each member's oldest open parked event, with `FOR UPDATE SKIP LOCKED` and a lease
       (B1's relay pattern)
- **Decision:** option 4.
  - **The parking table, `parked_event`** (migration 0003):
    - it keeps the original bytes, key and headers, and where the event came from
    - its status is `pending`, `in_flight`, `done` or `dead`
    - `attempts` counts permanent failures; `transient_failures` counts the rest
    - there's a lease, with first and last failure times
    - checks tie each status to its timestamp
    - `posting_app` can't delete a parked event or rewrite its bytes
  - **Failure kinds:**
    - **Transient** (ledger 5xx, timeout, 429, 401): exponential backoff with jitter, never dead-lettered.
    - **Permanent** (other 4xx): counted. At 5, the original bytes go to the DLQ topic, then the event is marked
      `dead`.
    - **A ledger 409, or undecodable bytes:** dead-lettered at once.
  - **A worker success:** the posting row, its outbox row and the parked event's `done` commit in one transaction,
    fenced on the worker's claim. A worker whose lease ran out rolls back.
  - **The retry worker** runs as its own container (`retry-worker`).
  - **The three `.retry.N` topics** are removed from the topic list.
- **Tradeoff:**
  - **The member waits behind its first failure.** One stuck event delays that member's later events, until it posts
    or dies, by design. Other members never wait.
  - **A transient failure never dead-letters,** so an event can wait forever during a long outage. It shows as the
    oldest parked age; the alert on that is M4.
  - **The parking table is one more table** to retain and watch.
  - **An existing stack keeps the unused retry topics** until Kafka is recreated.
- **Result:** verification log, M2 PR-B2b; repeat runs in `docs/evidence/m2-pr-b2b-repeat-runs.md`.
- **What would change this decision:** a member's events needing to proceed independently (then parking per stay,
  not per member), or a throughput need beyond one in-flight retry per member.

## ADR-0017: The checkout producer reports every delivery failure; idempotent, gapless, bounded retries
- **Context:** incident 2026-11-26 (`docs/incidents/2026-11-26-producer-silent-loss.md`).
  - **The bug:** `CheckoutProducer.send()` attached no delivery callback, and `flush()` only counted queued messages.
    A message Kafka refused or timed out was reported as sent.
  - **What it caused:** under a degraded broker, a member's first event was lost while later ones arrived, because
    librdkafka allows that gap by default. The later events posted ahead of the lost one.
  - **How it was found:** B2b's repeat runs (two-workers run 3: 6 events posted, 4 never arrived).
- **Options considered:**
  1. Read delivery reports only.
  2. Delivery reports plus idempotence and `acks=all`.
  3. Option 2 plus `enable.gapless.guarantee` and a bounded `delivery.timeout.ms`.
  4. Transactions: more than one topic doesn't need atomic writes here.
- **Decision:** option 3.
  - **Delivery reports:** every message gets a delivery callback. `send()` (and `flush()` for a batch) raises
    `DeliveryFailed` for any event refused, timed out, with no report, or still queued, naming each one. It is never
    a silent success.
  - **Settings:** `enable.idempotence=true`, `acks=all`, `enable.gapless.guarantee=true`,
    `max.in.flight.requests.per.connection=5`, `delivery.timeout.ms` (30 s by default).
  - **The tests' producer uses the same settings.**
- **Tradeoff:**
  - **A fatal error leaves the producer unusable.** Gapless turns a possible gap into one, so the caller must build a
    new producer.
  - **Sending waits for acknowledgements from all in-sync replicas.** With one broker that costs little; with
    replication it adds latency.
  - **A failed send is now an exception** the caller must handle, which is the point.
- **Result:** verification log, M2 PR-B2b.
  - **Before the fix:** on the real stack, `send()` returned normally for a refused event.
  - **After the fix:**
    - unit and real-stack tests pass: a nonexistent topic → `UNKNOWN_TOPIC`; an unreachable broker →
      `DeliveryFailed` after the delivery timeout
    - with a fault proxy cutting acknowledgements, 0 duplicates and per-member order kept, while the non-idempotent
      control showed 37 duplicates from the same fault
- **What would change this decision:** writing several topics atomically (then transactions), or a producer that must
  keep going after a fatal error (then recreate it automatically, with an alert).

## ADR-0018: Corrections credit the difference, through the same parking path; the schema gate runs inside CI's integration job
- **Context:** M2 PR-C builds RFC-0001 D10 (corrections), PIPE-09/10 (seeds, the load generator) and DEL-07 (the
  schema gate). D10 was written when retries used retry topics. ADR-0016 replaced those with parking.
- **Options considered:**
  - **Corrections:**
    1. A separate correction consumer.
    2. The same posting path, with a pure rule (`events.plan_credit`) used by both the consumer and the retry worker.
  - **Stale revisions:**
    1. A log line only.
    2. A `skipped_event` table: queryable, so the investigator (M6) can cite a stored row.
  - **The schema gate:**
    1. A sixth CI job, which also needs a change to `main`'s protection.
    2. A step in the `integration` job, which already runs a registry.
- **Decision:** option 2 in each case.
  - **The credit rule:**
    - a correction credits the signed difference from the stay's latest posted revision, under the ledger key
      `stay_id:revision`
    - a revision at or below the latest posted one is recorded in `skipped_event` and not credited
    - a correction with nothing posted for its stay parks as `original_missing`, a permanent failure, so it's
      dead-lettered after 5 attempts
    - a redelivery gets the same plan, so the ledger replays, not credits twice
  - **Seeds:** `seed.stays()` allocates stay IDs in sequence and derives event IDs from the seed. The old
    `synthetic_events` drew random stay IDs, so two members could share one: the second stay was then treated as a
    duplicate and refused with a 409. It now delegates to `seed.stays()`.
  - **Deferred:** the ledger `members` table that RFC-0001 change 6 moved to PR-C. Nothing in M2 reads it, and the
    ledger doesn't validate members. It goes in the milestone whose scenario needs it (M3), recorded in the backlog.
    The owner confirmed the deferral on 2026-11-27.
- **Tradeoff:**
  - **A correction that arrives before its original:** the original, arriving later for the same member, parks
    behind it. It posts only once the correction is dead-lettered, and the correction then needs a replay (M7, with
    approval).
  - **The local schema check is structural and conservative:** flat records, exact logical types. The registry
    remains the authority.
  - **Where the gate runs:** its local check is offline (unit tests, every CI run); its registry step needs a
    registry, so it runs in CI's integration job and against the local stack.
- **Result:** verification log, M2 PR-C.
- **What would change this decision:** corrections often arriving before originals (then let an original overtake a
  waiting correction of its own stay), or nested schemas (then a real compatibility library for the local check).

## ADR-0019: Adopt RFC-0002: pre-registration, scenarios, the read-only investigator and approved replay as one program
- **Context:** the owner asked for "Milestone 3: a read-only AI incident investigator plus human-approved replay
  without double-posting" (2026-11-27). In the spec that is three milestones: M3 (pre-registration, triggers), M6
  (the investigator) and M7 (recovery). Four scenarios also need evidence that only M4 was going to build.
- **Options considered:**
  - **Numbering:**
    1. Renumber the repo so the investigator is M3.
    2. Keep the spec's numbers and run the request as phases across M3, M6 and M7.
  - **M4 gaps (lag, "what changed", stored logs, alert rules):**
    1. Wait for M4, leaving scenarios S09, S12, S17 and S18 without evidence.
    2. Build a minimal version of each now; leave Prometheus, Grafana, Tempo and the Collector in M4.
  - **Kafka access for the investigator:**
    1. A code-level check only.
    2. SASL and the standard authorizer in the local stack, with a read-only principal.
  - **The ledger `members` table** (deferred to M3 by ADR-0018):
    1. Build it now.
    2. Move it to v2: none of the 18 scenarios needs an unknown-member failure.
  - **Freezing the pre-registration:**
    1. Git order only.
    2. Git order plus a lock file of SHA-256 hashes, so any later edit is a visible commit.
- **Decision:** option 2 in each case. Approved by the owner on 2026-11-27, with three additions:
  - the plan states explicitly that the investigator can never write, replay or post; that a replay needs a
    person's approval bound to the exact events; and that tests prove a replay can't double-post (RFC-0002, "The
    three guarantees")
  - one live run is pre-approved (Claude Haiku 5.5, the 18 dev scenarios, 3 runs each, plus the injection cases)
    with a hard cap of $3; the price is re-checked on the official pricing page and the estimate confirmed with the
    owner before the run
  - real-stack batches in Phases 2, 4 and 5 start only after the quiet check and the owner's OK
- **Tradeoff:**
  - **The request spans three spec milestones,** so the status table shows M3, M6 and M7 moving together, and
    arms A and B in full (M5) and the 60-incident benchmark (M9) still come later.
  - **The minimal M4 pieces are not M4:** no dashboards, no Prometheus rules, no trace backend yet.
  - **SASL changes how every service connects** and adds local-only passwords. It is plaintext SASL on loopback,
    labelled dev-only.
  - **Approval has no real sign-in** until M8: local principals through a CLI and an API.
  - **The lock file can still change until the first arm or investigator commit.** That is on purpose: a trigger
    may show a catalog entry to be wrong. Every change is a visible commit; after that point only dated amendments
    that never change a ground truth.
- **Result:** RFC-0002; `tests/test_preregistration.py`; verification log, M3 sections.
- **What would change this decision:** a scenario that needs an unknown member (then the `members` table comes
  back); SASL proving unreliable on Docker Desktop (then a documented code-level check, with the owner's OK); the
  owner wanting the web approval screen before replay (then M8's sign-in moves ahead of Phase 5).

## ADR-0020: The slow scenarios run on a real stack in GitHub Actions, as a workflow that is not a required check
- **Context:** 12 of the 18 scenarios restart containers, cut a database role's login or flap a consumer group, and
  take about five minutes together. The plan was a batch on the owner's laptop. The laptop is shared with other
  stages' paid benchmarks, and the owner's standing order (2026-11-27) is to run real-stack and Docker work in CI
  wherever possible. CI already starts the same stack for the required real-stack job.
- **Options considered:**
  1. Run the batch on the laptop when it is free.
  2. Add the 12 scenarios to the required "Real Kafka, Karapace and Postgres" job.
  3. A separate workflow, triggered when scenario, pipeline, compose or migration files change and on demand, not
     required for merging.
- **Decision:** option 3.
  - `tests/test_scenarios_batch.py`, marked `batch` (and `postgres`, `kafka`, so a skip is still a failure).
  - `scripts/run_integration.py` leaves `batch` out by default and selects only it with `--batch`.
  - `.github/workflows/scenario-batch.yml` starts the stack with throwaway values, runs the batch, and uploads the
    run manifests and the stack logs as an artifact for 30 days.
  - The six fast scenarios stay in the required job.
  - A pull request that changes scenario code is merged only after its batch run is green, by the builder's own
    rule: auto-merge goes on after that run, since the protection doesn't wait for it.
- **Tradeoff:**
  - **Not required, so it can be skipped by mistake.** A change outside the listed paths that breaks a slow
    scenario is caught only at the next batch run.
  - **GitHub's runners are not the owner's machine.** Timing differs (verification log M3 #7 is one case where a
    faster runner found a race the laptop hid), so waits tuned here may be tight elsewhere.
  - **Evidence lives in two places:** the test output is copied into `docs/evidence/`; the manifests and stack logs
    are in the run's artifact and expire after 30 days.
  - **Making it required** would add about six minutes to every pull request and a new required check to the
    branch protection (ADR-0013).
- **Result:** verification log, M3 Phase 2 (#13 onwards); `docs/evidence/m3-scenario-batch-ci-run-*.txt`.
- **What would change this decision:** a slow scenario breaking unnoticed (then make the workflow required, or run
  it nightly), or the batch growing past the job's 45-minute limit (then split it).

## ADR-0021: Kafka asks every client for a login, and the broker enforces a per-identity access list
- **Context:** RFC-0002's first guarantee is that the investigator can never write, replay or post. Until now
  every Kafka listener was plain: any process that reached the broker could produce to any topic, so the guarantee
  rested on the investigator's own code. The owner approved turning on authentication and ACLs in the local stack
  (2026-11-27).
- **Options considered:**
  - **Where the guarantee lives:**
    1. In code only (the investigator has no produce call).
    2. In the broker: a login per identity, and an access list the broker enforces.
  - **Mechanism:**
    1. SASL/PLAIN, with the users in the broker's own settings.
    2. SASL/SCRAM, with credentials stored in the cluster's metadata.
    3. mTLS.
  - **The controller listener:**
    1. Plain, not published to the host, as in Apache Kafka's own single-node SASL example.
    2. SASL too.
  - **Tests on scratch topics:**
    1. Grant the service identities rights on a `test.` prefix.
    2. Tests' own clients log in as the admin; separate tests log in as each identity against the real topics.
- **Decision:** the second option for where the guarantee lives, and the first for the mechanism and the controller
  listener; the second for tests.
  - **Identities** (`app/pipeline/kafka_auth.py`): `admin` (the broker, topic and ACL creation, scenarios, tests),
    `producer`, `posting` (the posting service and the retry worker), `relay`, `registry`, `investigator`,
    `replayer`. Each has its own `KAFKA_<NAME>_PASSWORD`, and each container is given only its own.
  - **The access list is data** (`kafka_auth.ACLS`), applied by `kafka-init` after it creates the topics. A
    principal with no matching entry is refused: `allow.everyone.if.no.acl.found` stays off.
  - **The investigator** may describe and read the three pipeline topics and describe the posting group. It has no
    write, create, alter or delete entry, and can't commit an offset.
  - **One function builds every client's settings** (`client_config(principal, bootstrap)`). Without that
    principal's password in the environment the settings are plain, which is what unit tests use.
  - **Super users:** `User:admin` and `User:ANONYMOUS`. Only the controller listener is plain, so only the broker
    itself can be anonymous; every listener a client can reach requires a login.
- **Tradeoff:**
  - **No TLS:** passwords cross the loopback interface and the compose network in clear text. Local stack only; a
    hosted stack needs SASL over TLS (or SCRAM or mTLS) and is v2.
  - **The controller listener is plain and its principal is a super user.** It isn't published to the host, but
    another container on the compose network could reach it. Accepted for a local stack; named in the threat model
    when that is written (SEC-08).
  - **PLAIN keeps the passwords in the broker's settings.** Rotating one means restarting the broker.
  - **Seven more local values in `.env`**, and the broker's start now depends on all of them.
  - **Tests run as the admin on scratch topics,** so they don't exercise the service identities' rights. The
    access-list tests do that, against the real topics, with writes the broker must refuse.
  - **`ensure_acls` only adds.** An entry removed from the list stays on a running broker until it is deleted by
    hand or the Kafka container is recreated (it has no volume). A test compares the broker's list with the code's.
- **Result:** `tests/test_kafka_auth.py` (offline), `tests/test_kafka_acls_real.py` (real stack); verification
  log, M3 Phase 2.
- **What would change this decision:** a hosted deployment (then TLS and per-broker credentials), or needing to
  rotate a login without a broker restart (then SCRAM).

## ADR-0022: One read-only evidence layer, with the guarantee in Postgres and the broker, not in the reader's code
- **Context:** RFC-0002 Phase 3. The rules baseline and the investigator must judge the same evidence, and the
  investigator must never be able to write. ADR-0021 put that guarantee in the broker for Kafka. The databases
  still had no reader role: any read would have used a role that can also write.
- **Options considered:**
  - **Who reads:**
    1. Each arm has its own queries.
    2. One layer (`app/evidence/`) that both arms use, outside `app/arms/` and `app/investigator/`, so building it
       does not freeze the pre-registration.
  - **Where "read-only" lives:**
    1. In the layer's code (it only issues SELECTs).
    2. In Postgres: a role per database with SELECT grants only, and read-only transactions by default.
  - **Raw payload bytes of a parked event:**
    1. Readable.
    2. A view without them.
    3. Column-level SELECT on the table, leaving out `raw_key` and `raw_value`.
  - **What a read returns:**
    1. Rows.
    2. Evidence items with a stable ID (`kind:where`), a time, and clipped text fields.
- **Decision:** option 2 for who reads, where it lives and what is returned; option 3 for the raw bytes.
  - **Roles** (`app/db/roles.py`): `posting_investigator`, `ledger_investigator`, `ops_investigator`, one password
    (`INVESTIGATOR_DB_PASSWORD`). SELECT only, on named tables. `ALTER ROLE … SET default_transaction_read_only = on`.
    A session can switch that setting off for itself, so the grants are the guarantee and the setting is the second
    lock; a test does exactly that and is still refused.
  - **Fixed queries** (`app/evidence/store.py`): ten named reads, each one bounded SELECT with `:since` and
    `:limit`. No caller passes SQL. A read says when it hit its limit, and a snapshot lists what was cut.
  - **Topics** (`app/evidence/topics.py`): the `investigator` Kafka login, `assign` only (no group, no commit). An
    event carries its own `occurred_at` next to the broker's timestamp, as `occurred_minus_broker_seconds`: the only
    place S13's skew shows. An undecodable event says so; its bytes are never returned.
  - **Text someone else wrote** (log messages, error text, correlation IDs, questions, runbook text) is listed in
    `model.UNTRUSTED` and cut to 300 characters. It is a value, never an instruction.
  - **Snapshots:** the scenario tests take one after every trigger, as these logins, and the workflows upload them.
    The 18 dev snapshots are committed as fixtures (`benchmarks/snapshots/dev/`, read with `app/evidence/dev.py`),
    so the rules and the mock evaluation run offline.
  - **A dev incident is run 0 on a new stack** (`SCENARIO_DEV_RUNS=1` in the workflows), the catalog's default,
    and for S15 pair A. Pair B first appears in M9's dataset. The scenario tests wait 5 s after each reset and
    open the evidence window on a whole second, so a snapshot holds one incident only; an offline test fails if a
    fixture names a member from another scenario's block or lacks its catalog entry's stored evidence.
- **Tradeoff:**
  - **One password for three roles.** Simpler to hand to one process; a leak exposes all three read paths. They
    are read-only and the data is synthetic.
  - **Column-level grants mean `SELECT *` on `parked_event` fails** for the reader. Intended; a new column must be
    added to the readable list on purpose.
  - **A snapshot is a point in time,** taken when the trigger's last step ends. Two triggers ended before their
    evidence existed and were given a wait (S06, S10; verification log M3 Phase 3 #9 and #10).
  - **The dev incidents are clean by construction:** one scenario at a time, with a settle wait. Background noise
    and overlapping incidents are M9's variants, not these.
  - **Reading a topic from the start is bounded by a message limit,** so on a long-lived stack the oldest messages
    are left out and reported as such.
- **Result:** `tests/test_evidence_unit.py`, `tests/test_db_offline.py` (offline); `tests/test_evidence_postgres.py`,
  `tests/test_scenarios_real.py` (real stack; S05 and S13 assert on the snapshot); verification log, M3 Phase 3.
- **What would change this decision:** a hosted deployment (a password per role, from a secret manager), or
  evidence volumes that need pagination instead of one bounded read.
