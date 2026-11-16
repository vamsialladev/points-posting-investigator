# Implementation plan

**Approved by the owner on 2026-11-16, before any code** (standing rule 1). Every row in
`docs/requirements-matrix.md` carries the release below. Nothing in the spec is dropped; it is tiered (ADR-0002).

## 1. v1.0.0: the core proof plus a demo
The spec's Tier 1 (milestones 1–9) is entirely in v1. So the spec's rule "don't start a higher tier while a lower
tier's checks fail" still holds, and every v1 slice of a later milestone starts only once Tier 1 is green.

| M | v1 content | Design-heavy: plan first, wait for the owner |
|---|---|---|
| 1 | Workspace, continuity review, tracking files, `CLAUDE.md` / `AGENTS.md`, `.env.example`, preflight, fictional discovery | – |
| 2 | Kafka (KRaft) + schema registry + Postgres in Docker; checkout producer, posting service, **transactional outbox** + relay, idempotent ledger mock. Done when a duplicate-event test on real Kafka + Postgres shows no double credit | **yes** (RFC-0001) |
| 3 | **Pre-registration first**, in its own commit before any arm or investigator code: `docs/failure-catalog.md` (all 18 scenarios), `docs/hypotheses.md`, `benchmarks/thresholds.yaml`, `docs/benchmark-protocol.md`, `tests/test_preregistration.py`. Then trigger and reset commands for every scenario | **yes** (RFC-0002) |
| 4 | OpenTelemetry tracing across HTTP, Kafka headers and the database; structured logs stored in Postgres so citations point at rows; Prometheus metrics; Grafana dashboards and alert rules as code; the "what changed" feed; one runbook per alert | – |
| 5 | Arm A (a scripted operator following the runbooks) and arm B (the rules correlation engine) | – |
| 6 | Arm C, the investigator: nine read-only typed tools; the bounded state machine with every stop condition tested; citations; the mock provider; injection tests | **yes** (RFC-0003) |
| 7 | Recovery: DLQ replay, pause/resume a consumer, re-run the outbox relay. Preview; approval bound to a message-set hash; no self-approval; limits; kill switch; reconciliation; append-only audit | **yes** (RFC-0004) |
| 8 | UI (Jinja2 + HTMX) and local auth with the five roles, plus a **minimal automation slice**: alert → dedupe → idempotent incident → auto-investigation within limits, the daily budget and the kill switch → approval → replay → verify → affected-member list. Done when the Playwright end-to-end flow passes | – |
| 9 | Benchmark: generate ≥60 labelled incidents from M3's composition (dev / validation / held-out / stress); freeze the behaviour files; A/B/C on mock; Eval Harness export. **Live arm C only with the owner's OK and a stated cap**; otherwise NOT RUN | **yes** (RFC-0005) |
| 12 (slice) | Draft threat model; `SECURITY.md` with the OWASP LLM Top 10 mapping; redaction and log-injection tests | – |
| 13 (slice) | GitHub Actions CI, built up from M2 (ruff, mypy, pytest with Kafka and Postgres services, migration check, gitleaks, pip-audit, SBOM, Playwright, lychee) and `scripts\ci_local.ps1`. No cloud work | – |
| 16 (slice) | README in house style; Playwright-recorded demo, AI-narrated (labelled, not imitating the owner) with the owner's own-voice script, captions and a silent captioned version; case study, stage card with three verified metrics, OG image, all as website PRs the owner approves | – |
| 17 (v1 scope) | Clean clone → README quickstart → offline tests, benchmark and Playwright pass. Then tag v1.0.0 | – |

## 2. v2: what's next
- **M10 in full:**
  - alert-storm circuit breaker
  - mock Jira and Slack
  - the self-hosted n8n flow with signed webhooks and exported JSON
  - `docs/automation-decision.md`
  - optional real Slack, with the owner's OK
- **M11:**
  - the Stage 9 adapter. Stage 9 has no case flag field today, so this needs a small, reviewed Stage 9 PR
  - read-only MCP tools with the Stage 7 conventions
- **M12 in full:** rate limits, the full threat model, and the NIST AI RMF / OWASP mapping.
- **M13 in full:**
  - cloud options with sourced costs
  - Terraform (pinned image, validate only)
  - a deploy only with the owner's OK and a cap, verified live by Playwright
  - rollback docs
- **M14:** game days and one post-incident review.
- **M15:** handover and UAT documents.
- **M16 remainder:** drills in the case study, the coverage-map update, the Notes post, LinkedIn variants, résumé
  bullets, and the live link on the card.
- **Also v2:** the real-human timing study for arm A, and registering Stage 10 in eval-harness's `PROJECTS` allowlist
  (a separate eval-harness PR).

## 3. Money and accounts
v1 runs on this machine: Kafka, Postgres, the schema registry, Grafana, Prometheus and Tempo in Docker, plus mock AI
and local narration. Each of these waits for the owner's explicit OK, and those with spend also need a stated cap:
- any live model call
- any cloud resource or deploy
- any paid service
- any account creation
- the real Slack webhook
- creating the public GitHub repo
- merging website PRs

## 4. Safety (applies to M6–M9)
- **The investigator can only read.** Its tools are read-only, and a test asserts that the registry has no write
  method.
- **Recovery is proposed, then approved** in the authenticated app by someone other than the requester. The approval
  is bound to the message set, the approver, the expiry and the ledger state.
- **No double credit, at three layers:**
  1. The event ID is the idempotency key.
  2. The ledger is checked before replay.
  3. A **unique constraint** in the ledger mock's own table refuses a second credit.

  Tested with repeated, concurrent and crash-interrupted replays and duplicate Kafka delivery, all on real Kafka and
  Postgres.

## 5. Owner exercises (spec Part N), by milestone
| Milestone | Exercise |
|---|---|
| 2 | Explain at-least-once vs exactly-once; explain the outbox pattern |
| 3 | Add a new failure scenario with its ground truth |
| 4 | Write a new alert rule |
| 5 | Trigger a scenario and diagnose it yourself before reading any arm's report |
| 6 | Change a stop condition and see which test fails |
| 7 | Replay a DLQ batch safely; revoke the ledger credential and prove the old one fails |
| 9 | Interpret a benchmark failure; explain why the rules engine sometimes wins |
| 14 (v2) | Run a game day |
| 1 (now) | Verify that Claude Code refuses to read `.env` (see `docs/session-handoff.md`) |

## 6. Order of work inside a milestone
1. Plan (design-heavy only), then the owner's approval.
2. Tests, then the code to pass them.
3. The "done when" checks.
4. Tracking files.
5. Commit on a branch.
6. Merge with `--no-ff`, or a PR once the GitHub repo exists.
7. The 3-line summary.
