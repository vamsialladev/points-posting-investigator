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
- **What would change this decision:** nothing foreseen. It is a standing rule.
