# MASTER BUILD PROMPT: AI Points-Posting Incident Investigator
## Stage 10 of the simulated hotel-group engagement on vamsialla.com

> **How to use (Codex):** In a new repository:
> 1. Save this file as `docs/MASTER-SPEC.md` and commit it.
> 2. Start Codex in that folder and send: *"Read docs/MASTER-SPEC.md completely and follow it. Begin with Part 0 and Milestone 1."*
> 3. For later sessions, use the resume prompt in Appendix A.

---

## PART 0: Role, mission, rules

### 0.1 Role
Act as my senior Forward Deployed Engineer, reliability/SRE engineer, event-driven systems engineer, applied AI engineer, automation engineer, security engineer, and implementation mentor.

### 0.2 Mission
Build, verify, and hand over **AI Points-Posting Incident Investigator**, Stage 10 of the simulated hotel-group engagement on vamsialla.com.

**Storyline.**
- Stage 9 (Loyalty Support Modernization) found that some missing-points cases are caused by failures in the hotel group's **points-posting pipeline**: checkout events → posting service → loyalty ledger.
- Stage 10 builds that event-driven pipeline and simulates realistic integration failures.
- It then builds an **alert-triggered AI investigator and workflow automation** that:
  - Detects incidents.
  - Investigates automatically (read-only).
  - Cites evidence.
  - Notifies people.
  - Proposes a limited recovery for human approval.
  - Closes the loop by flagging the affected Stage 9 member cases.

**What Stage 10 must prove that stages 0–9 do not** (lead with these):
1. **Event-driven architecture:**
   - Kafka with versioned event schemas.
   - At-least-once delivery, consumer groups, offsets, dead-letter topics.
   - Transactional outbox and idempotent consumers.
   - Lag and backpressure.
2. **Observability:** OpenTelemetry traces across HTTP and Kafka, logs, metrics, dashboards, alerts, and correlation IDs end to end.
3. **AIOps:** AI incident investigation with:
   - Timeline reconstruction.
   - Facts vs. hypotheses.
   - Citations to stored telemetry.
   - Explicit uncertainty.
   - A "what changed recently" analysis.
4. **Autonomous-but-bounded AI automation:** alerts trigger investigations automatically, but the AI can only *read and recommend*. Humans approve every action. This is the key differentiator.
5. **Workflow automation integration:** alert → incident → ticket → investigation → notification → approval → recovery → verification → Stage 9 case follow-up. Built in the app *and* through one external automation platform (self-hosted n8n).
6. **A fair benchmark:** manual runbook investigation vs. rule-based alert correlation vs. AI-assisted investigation. Most AIOps demos skip the rules baseline; this one does not.
7. **Safe recovery:**
   - Dead-letter replay with preview.
   - Approval bound to the exact message set.
   - Idempotent ledger posting.
   - Reconciliation.
   - No exactly-once claims.
8. **A real cloud deployment** with a verified live link, only after I approve a budget.
9. **Incident-response maturity:** game-day drills, a post-incident review from an executed drill, SLOs vs. measured results, and on-call runbooks.

This is an **independent portfolio simulation with synthetic data**. Implement the system; do not stop at plans or scaffolding.

### 0.3 Working rules
- Inspect the workspace and any `AGENTS.md` first. Preserve existing work.
- Use current official documentation and pin compatible versions with a lockfile.
- Make reversible decisions autonomously and record them in `docs/decisions.md`. Ask only when blocked by a missing decision or authorization, and batch questions.
- **Never invent** results, users, incidents "from production", URLs, approvals, savings, or tool usage.
- **Never do the following without my explicit approval:**
  - Create paid resources.
  - Deploy.
  - Publish.
  - Push to remotes.
  - Send real messages.
  - Connect real accounts.
- **Never ask for secrets in chat.** Values go only in a local `.env`. Never open or print `.env`; use a preflight command that reports set/missing only.
- Never weaken or delete failing tests to get green. Generated code is not verified functionality.
- Mock AI and live AI results are always kept separate. Missing credentials produce "NOT RUN", never a pass.
- Use the same fictional hotel group, properties, and tier names as vamsialla.com and Stage 9.
- If a session ends, update the handoff files so the next session continues without restarting.

**Statuses:** Implemented and verified · Implemented but unverified · Simulated · Documentation-only · Manual step required · Blocked (prerequisite) · Deferred (reason).

**Tracking files:**
- `docs/implementation-plan.md`
- `docs/implementation-status.md`
- `docs/requirements-matrix.md` (IDs, tier, files, evidence, status)
- `docs/decisions.md`
- `docs/session-handoff.md`
- `docs/verification-log.md`
- `docs/known-limitations.md`
- `docs/backlog.md`

### 0.4 Resolved design decisions

| Topic | Decision |
|---|---|
| Language | **Python 3.12 for all services.** Java/Spring Boot services are **out of scope**; record them as a backlog idea only |
| Event platform | Kafka in Docker Compose (KRaft mode, no ZooKeeper). Schema registry for versioned schemas (verify current options, for example Confluent Schema Registry or Apicurio). Use a maintained Python client; verify the current recommended library |
| Observability | OpenTelemetry SDK + OpenTelemetry Collector → a local trace backend (Jaeger or Grafana Tempo), Prometheus metrics, Grafana dashboards, structured JSON logs to a queryable store (Loki or Postgres). Verify current versions. Use GenAI semantic conventions for model calls if usable, noting their stability status |
| App stack | FastAPI, Pydantic v2, PostgreSQL, SQLAlchemy 2.x, Alembic, Jinja2 + HTMX + CSS, durable database-backed jobs, pytest, Playwright, GitHub Actions |
| AI | Claude through an application-owned provider interface. A deterministic offline mock provider is the default |
| Automation | In-app event-driven automation engine (code-first, tested), **plus** one external flow in **self-hosted n8n** (free, Docker) to show integration with an automation platform. Notifications go to local mock Slack/Jira endpoints by default; a real Slack webhook only with my approval |
| Scope boundary | Stage 9 owns loyalty adjustments, the legacy A/B/C support benchmark, document AI, and the classical-ML baseline. Stage 10 does not rebuild them; it links to Stage 9 through an optional adapter |
| Reuse | Reuse Stage 9 and existing-stage conventions: honesty rules, status vocabulary, eval/benchmark format (export to the existing Eval Harness format), handoff templates, MCP conventions (roles, tenants, audit) |

### 0.5 Scope tiers

| Tier | Contents | Milestones |
|---|---|---|
| 1. Core proof | Pipeline, failures, observability, investigator, recovery, benchmark | 1–9 |
| 2. Automation and enterprise readiness | Automation and n8n, security hardening, Stage 9 loop, MCP tools, deployment | 10–13 |
| 3. Drills and handover | | 14–15 |
| 4. Portfolio | | 16–17 |

Rules:
- Don't start a higher tier while a lower tier's checks fail.
- New ideas go to `docs/backlog.md`, not into the build.

---

## PART A: Discovery (fictional, labeled)
Create `docs/discovery.md` and `docs/workflow.md`:
- **Stakeholders:**
  - Integration/platform engineers.
  - On-call SRE.
  - Loyalty operations lead (Stage 9 users).
  - Support supervisor.
  - Security.
  - Engineering manager.
- **FICTIONAL interview excerpts.**
- **Current workflow:** an alert arrives → manual log search → reading Kafka topics → guessing → manual replay scripts → no link back to affected members.
- **Proposed workflow.**
- **Pain points and hypotheses** to measure, not assume.
- **Success metrics:**
  - Time to diagnosis.
  - Root-cause accuracy.
  - Wrong recovery proposals.
  - Members affected and time to correct their points.
- **Scope, exclusions, risks, RACI.**
- **AI vs. rules decisions:** what stays deterministic (alert rules, replay eligibility, idempotency, authorization) vs. what AI does (correlate, explain, hypothesize, draft).

---

## PART B: The points-posting pipeline (built first, before any AI)

### B1. Services (all Python, small, explainable)
1. **Checkout event producer** (simulated property-management system): emits `stay.checked_out` events with versioned schemas and correlation IDs.
2. **Posting service (consumer):**
   - Validates the event.
   - Computes points deterministically.
   - Writes the posting with an **idempotency key** (event ID).
   - Publishes `points.posted` via a **transactional outbox**.
3. **Loyalty ledger service** (mock system of record):
   - Idempotent credit endpoint.
   - Status lookup.
   - Rate limits.
   - Configurable latency.
   - Credential expiry.
4. **Outbox relay:** publishes outbox rows to Kafka, with ordering and retry semantics documented.
5. **Investigator app:** UI, API, AI investigator, automation engine, recovery service, worker.

### B2. Event semantics (documented and tested)
- At-least-once delivery.
- Consumer groups and the offset commit strategy (commit after successful processing).
- Retry topics with backoff.
- Dead-letter topic with failure metadata (error class, attempt count, original offset, correlation ID).
- Schema evolution rules (backward/forward compatibility).
- Out-of-order and duplicate handling.
- Partition key choice and its consequences.
- **Document clearly:**
  - Where duplicates can occur.
  - Why idempotency keys at the ledger prevent duplicate credits.
  - Why exactly-once across the whole system is not claimed.

### B3. Data
- Synthetic members, stays, and postings are seeded consistently with Stage 9's shapes (via `docs/continuity.md`).
- A load generator produces configurable event rates.

---

## PART C: Failure scenarios (pre-registered catalog)
Create `docs/failure-catalog.md` and **commit it before building the investigator**. Each scenario has:
- A repeatable trigger command.
- Expected system behavior.
- Ground-truth root cause, or "insufficient evidence."
- The evidence it leaves (which logs, traces, metrics, events, config changes).
- The correct recovery.
- Affected members.
- Reset and cleanup commands.

Scenarios (at least these):
1. Invalid event schema (producer deployed a breaking change).
2. Duplicate event delivery.
3. Ledger timeout.
4. Ledger rate limiting (429).
5. Poison message routed to the DLQ.
6. Consumer crash and restart mid-processing.
7. Database transaction failure in the posting service.
8. Expired ledger credential (401).
9. Backlog and consumer lag from a slow dependency.
10. Outbox relay stopped (postings written but never published).
11. Out-of-order events (correction arrives before original).
12. Recent config change, for example a lowered timeout ("what changed" scenario).
13. Clock skew causing wrong waiting-period decisions.
14. Partition rebalance storm.
15. Two simultaneous issues (compound incident).
16. Multiple symptoms with **insufficient evidence** for one root cause (the correct answer is uncertainty plus next evidence to collect).
17. A log message containing **prompt-injection text** (must not change behavior).
18. A noisy alert with no real incident (the correct answer is "no incident, alert noise").

Include scenarios where the **rules baseline is enough** and AI adds nothing.

---

## PART D: Observability
- **OpenTelemetry tracing** across HTTP, Kafka produce/consume (context propagated in message headers), DB calls, and model calls.
- **Structured logs** with trace IDs and correlation IDs. No sensitive payloads; redaction filter tested.
- **Metrics:**
  - Throughput.
  - Error rates.
  - Consumer lag.
  - DLQ size.
  - Ledger latency.
  - Outbox backlog.
  - Postings per minute.
  - Investigation latency, tokens, and cost.
- **Grafana dashboards** (provisioned as code):
  - Pipeline health.
  - Kafka lag.
  - DLQ.
  - Investigator and automation.
  - AI usage and cost.
- **Alert rules** (as code), each with an owner and runbook link: lag threshold, DLQ growth, error-rate spike, ledger 401/429 bursts, outbox backlog, posting drop.
- **"What changed" feed:** a change log of config and deploys (simulated) that the investigator can query.

---

## PART E: AI investigator

### E1. Trigger
Automatic on alert (Part F), or manual by incident ID or correlation ID.

### E2. Read-only, typed, bounded tools
- `query_logs`
- `get_trace`
- `get_events` (topic/offset metadata, DLQ entries, never full sensitive payloads)
- `get_consumer_lag`
- `get_service_health`
- `get_metrics_window`
- `get_recent_changes`
- `search_runbooks` (versioned runbooks, Postgres full-text search)
- `get_affected_postings`

Each tool has:
- Pydantic schemas.
- Authorization.
- Timeouts.
- Bounded output (summaries plus IDs).
- Correlation IDs.

**No shell, SQL, network, or write tools.**

### E3. Bounded loop (state machine)
- Load context → call model → validate tool request → authorize → execute → persist observation → check budgets → continue or finish.
- **Stop conditions, each tested:**
  - Valid diagnosis.
  - Insufficient evidence.
  - Repeated calls without new evidence.
  - Step, token, or cost limit.
  - Deadline.
  - Cancellation.
  - Repeated failures.

### E4. Output (validated schema)
- Incident summary.
- Reconstructed timeline.
- **Observed facts** (each with a citation) vs. **hypotheses** (ranked).
- Most supported root cause or "insufficient evidence."
- Missing evidence and how to get it.
- Affected scope (members, postings).
- Recommended recovery from the allowed set, with preconditions.
- A draft incident report.

Rules:
- **Citations link to the stored log line, trace span, event metadata, metric snapshot, change record, or runbook section.**
- No invented telemetry. No confidence percentages.

### E5. Untrusted input
- Log and event content is untrusted. Injection text in logs must not change tool use or recommendations; tests assert on effects.

### E6. Fallback
- With the model unavailable, the rules baseline (Part H, arm B) still produces a correlation report.
- Prompts are versioned. Every run stores prompt, model, tools, tokens, latency, and stop reason.

---

## PART F: Workflow automation (key differentiator)

### F1. In-app automation engine (code-first, tested)
1. **Alert fires** → deduplicate and group (same correlation window or fingerprint) → **create or update an incident** (idempotent).
2. **Auto-start a read-only AI investigation**, subject to:
   - Per-incident and per-hour limits.
   - A daily model budget.
   - **Alert-storm protection** (grouping, cooldowns, circuit breaker).
3. Create a **ticket** in a mock Jira-compatible endpoint, and post a **notification draft** to a mock Slack-compatible endpoint containing the diagnosis summary, citations link, and approval link.
4. **A human approves or rejects** the proposed recovery in the app (never from the chat message alone; the link opens the authenticated app).
5. **Execute** the recovery (Part G) → **verify** (lag back to normal, DLQ drained, postings reconciled against the ledger) → **update** the ticket and notification → **close** with a draft post-incident review.
6. **Close the loop with Stage 9:** produce the list of affected members and postings. Through an optional adapter, flag the matching Stage 9 missing-points cases with "root cause: incident X; fixed by replay Y; verify ledger." Stage 9 still controls any adjustment through its own approval flow.

Every automation step:
- Is idempotent.
- Is audited.
- Is retry-safe.
- Has a kill switch.

### F2. External automation platform: self-hosted n8n (Docker)
- One flow: signed webhook from the investigator ("incident diagnosed") → n8n → format and route to the mock Slack and mock Jira → callback to the investigator with the delivery status.
- Verify the webhook signature on both sides, use idempotent callbacks, and keep credentials only in n8n's credential store or env.
- Export the flow JSON into the repo (no secrets).
- **Write a comparison** (`docs/automation-decision.md`): code-first engine vs. n8n vs. durable-workflow engines (for example Temporal), covering reliability, testability, ownership, and when a customer would choose each.
- Optional (Tier 3, needs my approval): a real Slack incoming webhook to a personal test workspace.

---

## PART G: Recovery controls
- **Allowed actions:**
  - DLQ replay of selected messages.
  - Pause/resume a consumer.
  - Re-run the outbox relay for stuck rows.

  Nothing else.
- **Preview:** exactly which messages and postings, their current ledger state, and what replay will do.
- **Approval binding:**
  - Approval is bound to a hash of the exact message set, plus the approver, expiry, and current ledger state.
  - Any change invalidates it.
  - The requester cannot self-approve.
- **Limits:** maximum batch size, attempt limits, and a kill switch.
- **Safe execution:**
  - Check the ledger before replay; already-posted items are skipped.
  - Idempotency keys make duplicates harmless.
- **Partial success:** per-message outcome. Uncertain outcomes go to reconciliation (status query before any retry).
- **Audit:** an append-only audit trail.
- **Scope:** recovery is restricted to the simulated environment.

---

## PART H: Benchmark (three arms, pre-registered)

### H1. Arms
- **A. Manual runbook investigation:** a scripted operator follows the runbooks, plus an optional real human timing study (counterbalanced; only real participants count).
- **B. Rule-based correlation:** a deterministic alert-correlation engine with fingerprint grouping, correlation-ID joins, known error signatures, and a "recent change within window" rule.
- **C. AI-assisted:** B's evidence plus the AI investigator.

### H2. Dataset
- **At least 60 labeled incidents**, generated from the Part C scenarios with varied timing, noise, and compound cases.
- Splits: dev / validation / held-out / stress, grouped to avoid leakage.
- Ground truth comes from the scenario definitions, never from a model.
- Versions and checksums recorded.

### H3. Pre-registered thresholds and hypotheses
`benchmarks/thresholds.yaml` and `docs/hypotheses.md` are committed before C is run:
- C improves top-1 root-cause accuracy over B by at least the threshold.
- C does not increase wrong recovery proposals.
- C correctly abstains on insufficient-evidence and noise cases.
- Cost and latency stay within limits.
- 100% of authorization, approval-binding, and duplicate-prevention tests pass.

### H4. Metrics
Report each with counts and denominators:
- Root-cause top-1 and top-3 accuracy.
- Citation correctness.
- Correct abstention and uncertainty.
- Coverage.
- **Wrong recovery proposals.**
- Time to diagnosis (simulated clock) and time to recovery.
- Affected members correctly identified.
- Tool calls.
- Tokens and cost per incident.

Also report: per-scenario breakdown, **where B beats or equals C**, and uncertainty estimates where justified.

### H5. Reporting
- Commands: `make bench ARM=a|b|c SPLIT=heldout PROVIDER=mock|live BUDGET=5`, plus a compare command.
- Reports are JSON plus Markdown.
- Export in the existing Eval Harness format.
- Live runs only with a key and budget; otherwise NOT RUN.
- Failure analysis classifies each failure as data, telemetry gap, retrieval, model, tool, rule, or infrastructure. Failing cases join the regression suite.
- No tuning on held-out data.

---

## PART I: Security
- **Authentication:** local auth with roles (`operator`, `incident_commander`, `approver`, `auditor`, `admin`), server sessions, CSRF, rate limits, object-level authorization.
- **Secrets:** secrets come only from env. Redaction in logs and traces is tested. Payloads are minimized before model calls.
- **Webhooks:** signed (n8n, mock Slack/Jira) with replay protection (timestamp plus nonce).
- **SSRF protection:** no model-selected URLs; allowlisted destinations only.
- **Injection tests:** log/event injection, approval tampering, replay of approval links, alert-storm cost exhaustion.
- **Threat model:** `docs/threat-model.md` covering trust boundaries (Kafka, collector, n8n, model provider, webhooks), risks, controls, and residual risks.
- **Standards:** map relevant NIST AI RMF and OWASP (ASVS, LLM/agentic) controls to evidence. No compliance claims.

---

## PART J: Tests
- **Unit:** rules engine, idempotency, approval hash, redaction, schema compatibility.
- **Integration with real local Kafka and Postgres** (Compose or testcontainers):
  - Publish/consume.
  - Duplicates.
  - Consumer crash/restart.
  - DLQ routing.
  - Retry topics.
  - Outbox consistency.
  - Trace propagation through Kafka.
  - Rebalance.
  - Lag.
- **Automation:** dedupe and grouping, storm limits, idempotent incident creation, n8n webhook signature and callback, kill switch.
- **Recovery:**
  - Approval invalidation.
  - Replay idempotency.
  - Partial replay failure.
  - Uncertain outcome → reconciliation.
  - Ledger shows no duplicate credits.
- **AI harness:** every stop condition, malformed tool args, injection in logs, missing telemetry, insufficient-evidence cases (on the mock provider).
- **Playwright:** alert → auto-incident → investigation with citations → approval by a different user → replay → verified recovery → Stage 9 follow-up list.
- **Offline commands:** `make test` and `scripts/test.ps1` run everything offline.

---

## PART K: Deployment and CI
- **Local:** Docker Compose profiles (`core`, `observability`, `automation`, `full`), migrations, seeds, scenario trigger and reset commands, health and readiness endpoints, graceful shutdown.
- **CI (GitHub Actions):**
  - ruff, mypy, pytest with Kafka and Postgres services.
  - Migration check.
  - gitleaks, pip-audit, container scan.
  - SBOM.
  - Playwright.
  - Least-privilege permissions. No paid key needed.
- **Cloud (live link):**
  1. Present two or three options with monthly cost estimates sourced from current official pricing, for example a single small VM running the Compose stack vs. a managed container service plus a managed or serverless Kafka-compatible service.
  2. Include teardown steps.
  3. **Deploy only after I approve the option and budget.**
  4. Public demo mode:
     - Synthetic data.
     - Mock AI by default, or live AI with a hard cap.
     - A "run a scenario" button limited by rate and budget.
     - Automatic reset.
     - No shared admin account.
  5. Verify the live URL with Playwright before adding the link.
- **IaC:** Terraform for the chosen option, validated locally. Never applied without approval.
- **Rollback:** application and migration rollback docs; schema-registry compatibility rules are part of the release gate.

---

## PART L: Drills, SLOs, handover
- **SLOs (proposed, kept separate from measured):** pipeline posting latency, DLQ age, investigation completion, recovery verification.
- **Game days (actual results in `docs/drills.md`):**
  - Ledger outage.
  - Credential expiry.
  - Poison-message flood.
  - Consumer crash.
  - Model outage (rules fallback).
  - n8n down (in-app notifications still work).
  - Alert storm (budget holds).
  - Database restore with measured time.
- **One full post-incident review** written from an executed drill: timeline, impact, root cause, what went well, action items.
- **Handover documents:**
  - On-call runbooks (each linked from its alert).
  - Ownership and escalation matrix.
  - Support handover.
  - Agent and approver UAT scripts.
  - Training guide.
  - Open-issue register.

---

## PART M: MCP reuse (small, Tier 2)
- Expose read-only investigation tools (`get_incident`, `get_timeline`, `search_runbooks`) using the Stage 7 MCP conventions: role decides tools, tenants are isolated, every call is audited.
- **No recovery tools over MCP.** Write auth tests.

---

## PART N: Personal proficiency (tracked separately)
At each milestone, explain what changed, why, how to verify it, the failure modes, and one exercise for me. Exercises:
- Trigger a scenario and diagnose it myself before reading the AI.
- Write a new alert rule.
- Add a new failure scenario with ground truth.
- Change a stop condition.
- Interpret a benchmark failure.
- Replay a DLQ batch safely.
- Explain at-least-once vs. exactly-once.
- Explain the outbox pattern.
- Revoke a credential.
- Run a game day.
- Explain why the rules engine sometimes wins.

---

## PART O: Portfolio (match vamsialla.com house style)
- **Project card:**
  - Real output example (an alert plus the AI diagnosis excerpt with citations), labeled "real output, synthetic data".
  - **Exactly three headline metrics** with denominators, runs, held-out results, and date and version: root-cause accuracy A vs. B vs. C, wrong recovery proposals or duplicate credits, and cost per investigated incident or time to diagnosis.
  - Links: case study, GitHub, demo video, and live app (only when verified).
- **Case study:**
  - Problem.
  - Storyline link to Stage 9.
  - Architecture and event semantics.
  - The automation flow.
  - Benchmark results including where rules beat AI.
  - Drills.
  - Limitations.
- **README:**
  - Labels and CI badge.
  - Three metrics.
  - Real output.
  - Demo GIF.
  - Quickstart (PowerShell and macOS/Linux).
  - Mermaid architecture.
  - What AI does and doesn't control.
  - Results table.
  - How to reproduce.
  - Security summary.
  - Limitations.
  - Links to other stages.
- **Demo video:**
  - Playwright-recorded flow: trigger failure → alert → auto-investigation → notification → approval → replay → verified recovery → Stage 9 follow-up → benchmark slide.
  - A **natural first-person narration script** I record myself (plain words, no hype, one honest limitation), timed to the recording, plus SRT captions and a silent captioned version.
  - Never use a synthetic voice imitating me.
- **Site integration (prepare only):** Stage 10 in the stage list and "How I work" table, OG image, stills, and an update to the portfolio coverage map showing which gaps Stage 10 closes (event-driven, observability, AIOps, automation, live deployment).
- **Drafts:** one Notes post (for example "When my rules engine beat the AI"), a LinkedIn post, and résumé bullets. Drafts only, using only verified numbers. **Never reuse employer metrics.**
- **Rule:** every number shown must trace to a stored result file.

---

## PART P: Milestones and "done when"

| # | Milestone | Done when |
|---|---|---|
| 1 | Workspace, continuity review (site, Stage 9 repo), tracking files, AGENTS.md, `.env.example`, preflight, discovery | Docs exist; preflight reports set/missing |
| 2 | Kafka, schema registry, Postgres, pipeline services, outbox, idempotent ledger | Checkout → posting → ledger flow works; duplicate-event test proves no double credit |
| 3 | Failure catalog committed, scenario triggers and resets | Every scenario triggers and resets deterministically |
| 4 | Observability stack, dashboards, alert rules, change feed | Traces span HTTP and Kafka; each scenario fires its expected alert |
| 5 | Rules correlation engine (arm B) and manual runbook arm (A) | A and B produce reports on all scenarios |
| 6 | AI investigator (arm C) with tools, loop, citations, mock provider | All stop-condition and injection tests pass on mock |
| 7 | Recovery controls | Approval binding, replay idempotency, partial failure, and reconciliation tests pass; ledger has no duplicates |
| 8 | UI vertical slice + auth | Playwright end-to-end flow passes |
| 9 | Benchmark (thresholds and hypotheses committed first) | A/B/C reports from actual runs; live marked NOT RUN unless executed |
| 10 | Automation engine + n8n flow | Storm limits, dedupe, and signed webhook tests pass; n8n flow JSON exported |
| 11 | Stage 9 loop adapter + MCP read-only tools | Affected-member list matches ground truth; MCP auth tests pass |
| 12 | Security hardening + threat model | Security tests pass |
| 13 | CI, IaC, cloud options and costs; deploy only if approved | CI-equivalent passes locally; live URL verified, or "awaiting approval" |
| 14 | Game days + post-incident review | Drills recorded with actual results |
| 15 | Handover and UAT docs | Docs exist and are linked from alerts |
| 16 | Portfolio package | Real screenshots and video; every number traces to a result file |
| 17 | Clean-install verification | Fresh clone → README quickstart → offline tests pass |

---

## APPENDIX A: Codex session kit

**AGENTS.md** (create in Milestone 1):
```markdown
# Stage 10: AI Points-Posting Incident Investigator (portfolio simulation)
Source of truth: docs/MASTER-SPEC.md.

Every session: read docs/implementation-status.md and docs/session-handoff.md; run `make test`
(or scripts/test.ps1); work only on the named milestone; run its "done when" checks; review the
diff; update requirements-matrix, status, verification-log, handoff; commit (never push without OK).

Rules: Part 0 honesty rules are non-negotiable. Never weaken tests. AI is read-only; recovery is
deterministic and human-approved. Never open or print .env. No paid resources, deploys, publishing,
real messages or pushes without my explicit OK. Record which tool did each piece of work.
Before each milestone, tell me whether it is design-heavy (Milestones 2, 6, 7, 9, 10) so I can
choose a higher reasoning setting.
```

**Kickoff:** "Read docs/MASTER-SPEC.md completely and follow it. Begin with Part 0 and Milestone 1."

**Each milestone:** "Continue with Milestone N from docs/MASTER-SPEC.md Part P. Run the test suite first and fix earlier failures. Implement, run the 'done when' checks, report exact commands and results, what is unverified or blocked, and one exercise for me. Update tracking files and commit."

**Resume:** "Read AGENTS.md, docs/MASTER-SPEC.md, docs/session-handoff.md and docs/implementation-status.md. Run the tests, summarize status in 5 lines, and continue with the next incomplete milestone."

**Final verification:** "Clone this repo into a temp folder, follow only the README quickstart, run all tests, the offline benchmark and Playwright, regenerate screenshots, and produce the final report with every item classified by status."

---

## APPENDIX B: `.env.example` variable names (no values)
Create `.env.example` with names and comments only.
- **Core:**
  - `APP_PROFILE`, `APP_SECRET_KEY`, `PUBLIC_DEMO_MODE`
  - `DATABASE_URL`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
- **Kafka:** `KAFKA_BOOTSTRAP_SERVERS`, `SCHEMA_REGISTRY_URL`
- **Ledger mock:** `LEDGER_API_URL`, `LEDGER_API_TOKEN`
- **AI:**
  - `AI_PROVIDER` (mock | anthropic)
  - `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`
  - `LLM_BUDGET_USD_PER_RUN`, `LLM_BUDGET_USD_DAILY`
- **Observability:** `OTEL_EXPORTER_OTLP_ENDPOINT`, `GRAFANA_ADMIN_PASSWORD`
- **Automation:**
  - `N8N_ENCRYPTION_KEY`, `N8N_WEBHOOK_URL`, `AUTOMATION_WEBHOOK_SECRET`
  - `MOCK_SLACK_URL`, `MOCK_JIRA_URL`
  - `SLACK_WEBHOOK_URL` (optional, real, only with approval)
- **Stage 9 adapter:** `STAGE9_API_URL`, `STAGE9_API_TOKEN` (optional)
- **Deployment:** `AWS_PROFILE`, `AWS_REGION` (SSO only, no long-lived keys)
- **Feature flags:** `FEATURE_LIVE_AI`, `FEATURE_AUTO_INVESTIGATE`, `FEATURE_RECOVERY_EXECUTION`, `FEATURE_N8N`

Empty values mean mock or Blocked. Never commit `.env`.

---

## APPENDIX C: Coverage checklist

| Source requirement | Covered in |
|---|---|
| Original generic prompt: order intake API, worker, mock downstream, investigator | Part B (adapted to the points-posting pipeline) |
| 10 original failure scenarios | Part C (1–9, 16), plus 8 more |
| Investigation workflow, citations, facts vs. hypotheses, no invented telemetry | Part E |
| DLQ replay with preview, binding, limits, audit, idempotency, partial success | Part G |
| Correlation IDs, retries, backoff, DLQ, offsets, outbox, shutdown, retention, redaction | Parts B, D, I, K |
| Interface pages | Parts E–G (UI built in Milestone 8; incident queue, detail, health, timeline, evidence, diagnosis, runbooks, preview, replay status, audit, eval results, mode indicator) |
| FDE docs (discovery, workflow, contracts, failure model, security, runbooks, handover, ADRs, matrix) | Parts A, C, I, L, 0.3 |
| Tests with real Kafka and Postgres, 30+ cases (raised to 60+) | Parts J, H |
| Manual vs. assisted timing, live budget, offline-first | Part H |
| Deployment, CI, AWS, backup/restore/rollback | Parts K, L |
| Portfolio package and 5-step demo | Part O |
| Storyline tie to Stage 9 | 0.2, F1 step 6, Part O |
| Rules-baseline benchmark | Part H |
| Workflow automation (in-app + n8n) instead of Java | 0.4, Part F |
| Real live deployment with budget approval | Part K |
| Site house style, Codex kit, env template, coverage map | Parts O, Appendices A–B |
