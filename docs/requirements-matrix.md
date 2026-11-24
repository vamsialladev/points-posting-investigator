# Requirements matrix

Every requirement in `docs/MASTER-SPEC.md` has one row, plus the owner's standing rules and the portfolio standards
(`CLAUDE.md`). Nothing is dropped: each row is either **v1** or **v2** ("what's next"; ADR-0002).

**How to read a row:**
- **Tier** is the spec's tier (0.5).
- **M** is the milestone that delivers it.
- **Status** uses the vocabulary in `docs/implementation-status.md`; `Planned (M#)` means no milestone has reached it
  yet.

`tests/test_repo_guidance.py` checks every row's release and status, and that every spec Part (0, A–P) has rows.

## Part 0: role, mission, rules; owner's standing rules

| ID | Requirement | Spec | Tier | Release | M | Implementation | Evidence | Status |
|---|---|---|---|---|---|---|---|---|
| P0-01 | Inspect the workspace first; preserve existing work | 0.3 | 1 | v1 | 1 | Workspace held only `.git` (no commits) and `docs/MASTER-SPEC.md`; both kept | `docs/verification-log.md` M1 #1 | Implemented and verified |
| P0-02 | Pin compatible versions with a lockfile | 0.3 | 1 | v1 | 1 | `pyproject.toml` (`~=`), `uv.lock` | `uv sync --frozen` in `scripts\ci_local.ps1` | Implemented and verified |
| P0-03 | Record reversible decisions in `docs/decisions.md`; ask only when blocked, batched | 0.3 | 1 | v1 | all | `docs/decisions.md` | `tests/test_repo_guidance.py::test_adrs_have_the_stage9_headings` | Implemented and verified |
| P0-04 | No paid resources, deploys, publishing, pushes, real messages or real accounts without explicit approval | 0.3, rule 5 | 1 | v1 | all | `CLAUDE.md` rules 5–6 | `tests/test_repo_guidance.py::test_claude_md_keeps_the_owners_standing_rules` | Implemented and verified |
| P0-05 | Never ask for secrets in chat; values only in `.env`; preflight reports set/missing only | 0.3, App B, rule 4 | 1 | v1 | 1 | `app/preflight.py`, `.claude/settings.json`, `scripts\new_env.ps1` | `tests/test_preflight.py::test_output_never_contains_values` | Implemented and verified |
| P0-06 | Never weaken tests; a check that scans or tests nothing must fail | 0.3, rule 7 | 1 | v1 | 1 | `tests/required_markers.py`, `app/env_leaks.py` (NOT RUN = exit 3), `scripts\secrets_scan.ps1` | `tests/test_required_markers.py`, `tests/test_env_leaks.py` | Implemented and verified |
| P0-07 | Mock and live results kept separate; missing credentials give NOT RUN, never a pass | 0.3 | 1 | v1 | 6, 9 | – | – | Planned (M6) |
| P0-08 | Same fictional hotel group, properties and tier names as the site and Stage 9 | 0.3 | 1 | v1 | 1, 2 | `docs/continuity.md` §3–4 (data arrives in M2) | `docs/continuity.md` | Implemented and verified |
| P0-09 | Handoff files updated so the next session continues without restarting | 0.3, rule 10 | 1 | v1 | all | `docs/session-handoff.md` | `tests/test_repo_guidance.py::test_tracking_files_exist` | Implemented and verified |
| P0-10 | Status vocabulary | 0.3 | 1 | v1 | 1 | `docs/implementation-status.md` | `tests/test_repo_guidance.py::test_every_matrix_row_has_a_release_and_a_known_status` | Implemented and verified |
| P0-11 | The eight tracking files | 0.3 | 1 | v1 | 1 | `docs/implementation-plan.md` … `docs/backlog.md` | `tests/test_repo_guidance.py::test_tracking_files_exist` | Implemented and verified |
| P0-12 | Python 3.12 for all services; Java/Spring Boot only as a backlog idea | 0.4 | 1 | v1 | 1 | `pyproject.toml` `requires-python`, ADR-0005, `docs/backlog.md` | `tests/test_repo_guidance.py::test_python_312_and_java_in_backlog` | Implemented and verified |
| P0-13 | Scope tiers; new ideas go to the backlog; no higher tier while a lower tier's checks fail | 0.5 | 1 | v1 | all | `docs/implementation-plan.md`, `docs/backlog.md` | `docs/implementation-plan.md` | Implemented and verified |
| P0-14 | `AGENTS.md` from Appendix A (Codex steps optional) | App A | 1 | v1 | 1 | `AGENTS.md` | `tests/test_repo_guidance.py::test_agents_md_points_to_claude_md` | Implemented and verified |
| P0-15 | `.env.example` with names and comments only (Appendix B) | App B | 1 | v1 | 1 | `.env.example` | `tests/test_preflight.py::test_template_names_match_known_variables`, `::test_template_defaults_are_mock_and_safe` | Implemented and verified |
| P0-16 | Continuity review: the live site and the Stage 9 repo are the source of truth | P (M1), owner | 1 | v1 | 1 | `docs/continuity.md` | `docs/verification-log.md` M1 #2–#4 | Implemented and verified |
| P0-17 | Claude Code is the builder; Codex steps kept as an optional exercise | owner | 1 | v1 | 1 | ADR-0001, `AGENTS.md` | `tests/test_repo_guidance.py::test_agents_md_points_to_claude_md` | Implemented and verified |
| P0-18 | Commits use the owner's noreply email | rule 6 | 1 | v1 | 1 | repo-local `user.email` | `docs/verification-log.md` M1 (git log check) | Implemented and verified |
| P0-19 | `CLAUDE.md` with the owner's ten standing rules | owner | 1 | v1 | 1 | `CLAUDE.md` | `tests/test_repo_guidance.py::test_claude_md_keeps_the_owners_standing_rules` | Implemented and verified |
| P0-20 | Ask before creating the public GitHub repo; branches, PRs, merge commits on green CI | rule 6 | 1 | v1 | 1 | Owner's OK 2026-11-16; public repo with secret scanning and push protection | `docs/verification-log.md` M1 #23–#24 | Implemented and verified |
| P0-21 | Secret deny rules also where the owner starts sessions (`C:\projects\project1`), outside every repo | rule 4, owner | 1 | v1 | 1 | `C:\projects\project1\.claude\settings.json` (not committed), ADR-0008; `*.env` blocked, `.env.example` readable and checked by `tests/test_env_template.py`, ADR-0009 | `docs/verification-log.md` M1 #19–#36; `tests/test_env_template.py::test_env_example_holds_no_real_looking_value`; `tests/test_secrets_hygiene.py::test_claude_code_is_denied_any_file_ending_in_env`; `tests/test_secrets_hygiene.py::test_every_env_file_in_the_repo_is_denied_to_read` | Implemented and verified |

## Part A: discovery (fictional, labelled)

| ID | Requirement | Spec | Tier | Release | M | Implementation | Evidence | Status |
|---|---|---|---|---|---|---|---|---|
| DISC-01 | Stakeholders: platform engineers, on-call SRE, loyalty ops lead, support supervisor, security, engineering manager | A | 1 | v1 | 1 | `docs/discovery.md` §2 | `tests/test_repo_guidance.py::test_discovery_covers_part_a` | Implemented and verified |
| DISC-02 | FICTIONAL interview excerpts | A | 1 | v1 | 1 | `docs/discovery.md` §3 | same | Implemented and verified |
| DISC-03 | Current and proposed workflow | A | 1 | v1 | 1 | `docs/workflow.md` | `tests/test_repo_guidance.py::test_workflow_has_current_and_proposed` | Implemented and verified |
| DISC-04 | Pain points and hypotheses to measure, not assume | A | 1 | v1 | 1 | `docs/discovery.md` §4 (DH1–DH6; formal benchmark hypotheses are M3) | `tests/test_repo_guidance.py::test_discovery_covers_part_a` | Implemented and verified |
| DISC-05 | Success metrics: time to diagnosis, root-cause accuracy, wrong recovery proposals, members affected and time to correct points | A | 1 | v1 | 1 | `docs/discovery.md` §5 | same | Implemented and verified |
| DISC-06 | Scope, exclusions, risks, RACI | A | 1 | v1 | 1 | `docs/discovery.md` §6–8 | same | Implemented and verified |
| DISC-07 | AI vs rules decisions | A | 1 | v1 | 1 | `docs/discovery.md` §9 | same | Implemented and verified |

## Part B: the points-posting pipeline

| ID | Requirement | Spec | Tier | Release | M | Implementation | Evidence | Status |
|---|---|---|---|---|---|---|---|---|
| PIPE-01 | Kafka (KRaft) and a schema registry in Docker Compose; a maintained Python client (verified in current docs) | 0.4 | 1 | v1 | 2 | `docker-compose.yml` (`apache/kafka:4.4.0`, `ghcr.io/aiven-open/karapace:6.2.4`), `app/pipeline/topics.py`, `app/pipeline/schemas.py`; `confluent-kafka` 2.16.1 (RFC-0001 D1–D3, ADR-0010) | `docs/verification-log.md` M2; `tests/test_kafka_stack.py::test_an_avro_event_round_trips_through_kafka_and_karapace`; `tests/test_kafka_stack.py::test_the_stack_has_every_pipeline_topic_with_three_partitions` | Implemented and verified |
| PIPE-02 | Checkout event producer: `stay.checked_out`, versioned schemas, correlation IDs | B1 | 1 | v1 | 2 | `app/pipeline/producer.py` (Avro v1 via the registry; key = member; headers `event_id`, `schema_version`, `correlation_id`, `traceparent`; idempotent producer) | `docs/verification-log.md` M2 PR-B2a; `tests/test_posting_service_unit.py::test_the_producer_keys_by_member_and_sets_the_headers`; `tests/test_posting_kafka.py::test_end_to_end_one_trace_id_from_producer_to_points_posted` | Implemented and verified |
| PIPE-03 | Posting service: validate, compute points deterministically, idempotency key = event ID, publish `points.posted` via a transactional outbox | B1 | 1 | v1 | 2 | `app/pipeline/posting.py` (posting + outbox in one transaction; offset committed after it; posting key `event_id`, ledger key `stay_id:revision` by the owner's change of 2026-11-23), `app/pipeline/events.py`, `app/pipeline/ledger_client.py`, ADR-0015 | `docs/verification-log.md` M2 PR-B2a; `docs/evidence/m2-pr-b2a-repeat-runs.md`; `tests/test_posting_kafka.py::test_one_event_gives_one_posting_one_outbox_row_and_one_published_message`; `tests/test_posting_kafka.py::test_a_db_failure_mid_transaction_writes_neither_row_and_the_event_is_retried`; `tests/test_posting_kafka.py::test_a_crash_after_the_db_commit_before_the_offset_commit_redelivers_and_stays_one_posting`; `tests/test_posting_kafka.py::test_eight_concurrent_copies_of_one_event_give_one_posting`; `tests/test_posting_kafka.py::test_eight_concurrent_resends_under_new_event_ids_give_one_credit_and_one_posting` | Implemented and verified |
| PIPE-04 | Loyalty ledger mock: idempotent credit, status lookup, rate limits, configurable latency, credential expiry | B1 | 1 | v1 | 2 | `app/ledger/` (core, store, api), own database with `UNIQUE(idempotency_key)` and an INSERT-only runtime role (RFC-0001 D9, D11; ADR-0011) | `docs/verification-log.md` M2; `tests/test_ledger_postgres.py::test_concurrent_credits_for_one_key_store_exactly_one`; `tests/test_ledger_postgres.py::test_the_ledger_runtime_role_cannot_change_or_remove_a_credit`; `tests/test_ledger_api.py::test_an_expired_token_is_a_401_for_credits_and_lookups`; `tests/test_ledger_api.py::test_over_the_rate_limit_is_a_429_with_retry_after`; `tests/test_ledger_smoke.py::test_the_running_ledger_credits_once_and_refuses_a_wrong_token` | Implemented and verified |
| PIPE-05 | Outbox relay with ordering and retry semantics documented | B1 | 1 | v1 | 2 | `app/pipeline/relay.py` (several relays; each member's oldest open row; `FOR UPDATE SKIP LOCKED` + lease; transient vs permanent failures; dead-letter at max attempts), migration `0002`, ADR-0014 | `docs/verification-log.md` M2 PR-B1; `docs/evidence/m2-pr-b1-repeat-runs-first.md`; `docs/evidence/m2-pr-b1-repeat-runs-outage.md`; `tests/test_relay_kafka.py::test_two_relays_never_claim_the_same_row_and_each_row_is_published_once`; `tests/test_relay_kafka.py::test_a_crash_after_publish_before_marking_publishes_twice_and_readers_dedupe`; `tests/test_relay_kafka.py::test_per_member_order_holds_while_one_row_retries`; `tests/test_relay_kafka.py::test_a_poison_row_is_dead_lettered_after_max_attempts_and_nothing_else_waits_for_good`; `tests/test_relay_kafka.py::test_kafka_down_for_60_seconds_the_outbox_grows_then_drains_with_nothing_lost` | Implemented and verified |
| PIPE-06 | Investigator app: UI, API, AI investigator, automation engine, recovery service, worker | B1 | 1 | v1 | 6–8 | – | – | Planned (M6) |
| PIPE-07 | Event semantics documented and tested: at-least-once, consumer groups, commit after processing, retry topics with backoff, DLQ metadata, schema evolution, out-of-order and duplicates, partition key | B2 | 1 | v1 | 2 | – | – | Planned (M2) |
| PIPE-08 | Document where duplicates occur, why ledger idempotency keys prevent double credit, and why exactly-once is not claimed | B2 | 1 | v1 | 2 | – | – | Planned (M2) |
| PIPE-09 | Synthetic members, stays and postings consistent with Stage 9's shapes | B3 | 1 | v1 | 2 | – | – | Planned (M2) |
| PIPE-10 | Load generator with configurable event rates | B3 | 1 | v1 | 2 | – | – | Planned (M2) |

## Part C: failure scenarios (pre-registered)

| ID | Requirement | Spec | Tier | Release | M | Implementation | Evidence | Status |
|---|---|---|---|---|---|---|---|---|
| FAIL-00 | `docs/failure-catalog.md` committed before any arm or investigator code; each scenario has trigger, expected behaviour, ground truth, evidence, recovery, affected members, reset | C | 1 | v1 | 3 | – | – | Planned (M3) |
| FAIL-01 | Invalid event schema (breaking producer change) | C | 1 | v1 | 3 | – | – | Planned (M3) |
| FAIL-02 | Duplicate event delivery | C | 1 | v1 | 3 | – | – | Planned (M3) |
| FAIL-03 | Ledger timeout | C | 1 | v1 | 3 | – | – | Planned (M3) |
| FAIL-04 | Ledger rate limiting (429) | C | 1 | v1 | 3 | – | – | Planned (M3) |
| FAIL-05 | Poison message routed to the DLQ | C | 1 | v1 | 3 | – | – | Planned (M3) |
| FAIL-06 | Consumer crash and restart mid-processing | C | 1 | v1 | 3 | – | – | Planned (M3) |
| FAIL-07 | Database transaction failure in the posting service | C | 1 | v1 | 3 | – | – | Planned (M3) |
| FAIL-08 | Expired ledger credential (401) | C | 1 | v1 | 3 | – | – | Planned (M3) |
| FAIL-09 | Backlog and consumer lag from a slow dependency | C | 1 | v1 | 3 | – | – | Planned (M3) |
| FAIL-10 | Outbox relay stopped (postings written, never published) | C | 1 | v1 | 3 | – | – | Planned (M3) |
| FAIL-11 | Out-of-order events (correction before original) | C | 1 | v1 | 3 | – | – | Planned (M3) |
| FAIL-12 | Recent config change, e.g. a lowered timeout ("what changed") | C | 1 | v1 | 3 | – | – | Planned (M3) |
| FAIL-13 | Clock skew causing wrong waiting-period decisions | C | 1 | v1 | 3 | – | – | Planned (M3) |
| FAIL-14 | Partition rebalance storm | C | 1 | v1 | 3 | – | – | Planned (M3) |
| FAIL-15 | Two simultaneous issues (compound incident) | C | 1 | v1 | 3 | – | – | Planned (M3) |
| FAIL-16 | Insufficient evidence for one root cause (correct answer: uncertainty plus next evidence) | C | 1 | v1 | 3 | – | – | Planned (M3) |
| FAIL-17 | Log message with prompt-injection text (must not change behaviour) | C | 1 | v1 | 3 | – | – | Planned (M3) |
| FAIL-18 | Noisy alert with no real incident (correct answer: alert noise) | C | 1 | v1 | 3 | – | – | Planned (M3) |
| FAIL-19 | Scenarios where the rules baseline is enough and AI adds nothing, named in advance | C | 1 | v1 | 3 | – | – | Planned (M3) |

## Part D: observability

| ID | Requirement | Spec | Tier | Release | M | Implementation | Evidence | Status |
|---|---|---|---|---|---|---|---|---|
| OBS-01 | OpenTelemetry tracing across HTTP, Kafka produce/consume (context in headers), DB and model calls | D | 1 | v1 | 4 | – | – | Planned (M4) |
| OBS-02 | Structured logs with trace and correlation IDs; no sensitive payloads; redaction filter tested | D | 1 | v1 | 4 | – | – | Planned (M4) |
| OBS-03 | Metrics: throughput, error rates, lag, DLQ size, ledger latency, outbox backlog, postings/min, investigation latency, tokens, cost | D | 1 | v1 | 4 | Part: the relay's `/metrics` (outbox lag, backlog, dead rows, publish failures; `app/pipeline/relay.py`, M2 PR-B1); the rest and Prometheus in M4 | – | Planned (M4) |
| OBS-04 | Grafana dashboards as code: pipeline health, Kafka lag, DLQ, investigator and automation, AI usage and cost | D | 1 | v1 | 4 | – | – | Planned (M4) |
| OBS-05 | Alert rules as code, each with an owner and runbook link (lag, DLQ growth, error spike, ledger 401/429, outbox backlog, posting drop) | D | 1 | v1 | 4 | – | – | Planned (M4) |
| OBS-06 | "What changed" feed of simulated config changes and deploys, queryable by the investigator | D | 1 | v1 | 4 | – | – | Planned (M4) |
| OBS-07 | GenAI semantic conventions for model calls where usable, with their stability status noted | 0.4 | 1 | v1 | 6 | – | – | Planned (M6) |

## Part E: AI investigator

| ID | Requirement | Spec | Tier | Release | M | Implementation | Evidence | Status |
|---|---|---|---|---|---|---|---|---|
| AI-01 | Trigger: automatic on alert, or manual by incident or correlation ID | E1 | 1 | v1 | 6, 8 | – | – | Planned (M6) |
| AI-02 | Nine read-only typed tools (`query_logs` … `get_affected_postings`) with Pydantic schemas, authorization, timeouts, bounded output, correlation IDs; no shell, SQL, network or write tools | E2 | 1 | v1 | 6 | – | – | Planned (M6) |
| AI-03 | Bounded state-machine loop; every stop condition tested (diagnosis, insufficient evidence, no new evidence, step/token/cost limit, deadline, cancellation, repeated failures) | E3 | 1 | v1 | 6 | – | – | Planned (M6) |
| AI-04 | Validated output: summary, timeline, cited facts vs ranked hypotheses, root cause or "insufficient evidence", missing evidence, scope, recovery from the allowed set, draft report | E4 | 1 | v1 | 6 | – | – | Planned (M6) |
| AI-05 | Citations to stored log lines, spans, event metadata, metric snapshots, change records, runbook sections; no invented telemetry; no confidence percentages | E4 | 1 | v1 | 6 | – | – | Planned (M6) |
| AI-06 | Log and event content is untrusted; injection must not change tool use or recommendations (tests assert on effects) | E5 | 1 | v1 | 6 | – | – | Planned (M6) |
| AI-07 | With the model unavailable, the rules baseline still produces a correlation report | E6 | 1 | v1 | 6 | – | – | Planned (M6) |
| AI-08 | Versioned prompts; each run stores prompt, model, tools, tokens, latency and stop reason | E6 | 1 | v1 | 6 | – | – | Planned (M6) |
| AI-09 | Application-owned provider interface; deterministic offline mock provider is the default | 0.4 | 1 | v1 | 6 | – | – | Planned (M6) |

## Part F: workflow automation

| ID | Requirement | Spec | Tier | Release | M | Implementation | Evidence | Status |
|---|---|---|---|---|---|---|---|---|
| AUTO-01 | Alert → deduplicate and group → create or update an incident (idempotent) | F1.1 | 2 | v1 | 8 | – | – | Planned (M8) |
| AUTO-02 | Auto-start a read-only investigation within per-incident and per-hour limits and a daily model budget | F1.2 | 2 | v1 | 8 | – | – | Planned (M8) |
| AUTO-03 | Alert-storm protection: grouping and cooldowns | F1.2 | 2 | v1 | 8 | – | – | Planned (M8) |
| AUTO-04 | Alert-storm protection: circuit breaker | F1.2 | 2 | v2 | 10 | – | – | Planned (v2) |
| AUTO-05 | Ticket in a mock Jira-compatible endpoint; notification draft to a mock Slack-compatible endpoint (summary, citations link, approval link) | F1.3 | 2 | v2 | 10 | – | – | Planned (v2) |
| AUTO-06 | A human approves or rejects in the authenticated app, never from a chat message | F1.4 | 2 | v1 | 8 | – | – | Planned (M8) |
| AUTO-07 | Execute → verify (lag normal, DLQ drained, postings reconciled) → close with a draft post-incident review | F1.5 | 2 | v1 | 8 | – | – | Planned (M8) |
| AUTO-08 | Ticket and notification updated through recovery and close | F1.5 | 2 | v2 | 10 | – | – | Planned (v2) |
| AUTO-09 | Affected members and postings list for Stage 9 follow-up | F1.6 | 2 | v1 | 8 | – | – | Planned (M8) |
| AUTO-10 | Optional adapter flags the matching Stage 9 cases ("root cause: incident X; fixed by replay Y; verify ledger"); Stage 9 keeps its own approval flow. Needs a reviewed Stage 9 PR (no flag field today) | F1.6 | 2 | v2 | 11 | – | – | Planned (v2) |
| AUTO-11 | Every automation step idempotent, audited, retry-safe, with a kill switch | F1 | 2 | v1 | 8 | – | – | Planned (M8) |
| AUTO-12 | n8n flow: signed webhook → n8n → mock Slack/Jira → callback with delivery status; signatures checked both sides; idempotent callbacks | F2 | 2 | v2 | 10 | – | – | Planned (v2) |
| AUTO-13 | n8n flow JSON exported into the repo (no secrets) | F2 | 2 | v2 | 10 | – | – | Planned (v2) |
| AUTO-14 | `docs/automation-decision.md`: code-first vs n8n vs durable-workflow engines | F2 | 2 | v2 | 10 | – | – | Planned (v2) |
| AUTO-15 | Optional real Slack incoming webhook to a personal test workspace (owner approval only) | F2 | 3 | v2 | 10 | – | – | Planned (v2) |

## Part G: recovery controls

| ID | Requirement | Spec | Tier | Release | M | Implementation | Evidence | Status |
|---|---|---|---|---|---|---|---|---|
| REC-01 | Allowed actions only: DLQ replay of selected messages, pause/resume a consumer, re-run the outbox relay | G | 1 | v1 | 7 | – | – | Planned (M7) |
| REC-02 | Preview: which messages and postings, current ledger state, what replay will do | G | 1 | v1 | 7 | – | – | Planned (M7) |
| REC-03 | Approval bound to a hash of the exact message set, approver, expiry and ledger state; any change invalidates it | G | 1 | v1 | 7 | – | – | Planned (M7) |
| REC-04 | The requester cannot self-approve | G | 1 | v1 | 7 | – | – | Planned (M7) |
| REC-05 | Limits: maximum batch size, attempt limits, kill switch | G | 1 | v1 | 7 | – | – | Planned (M7) |
| REC-06 | Safe execution: ledger checked before replay, posted items skipped, idempotency keys; a unique constraint at the ledger | G | 1 | v1 | 7 | – | – | Planned (M7) |
| REC-07 | Per-message outcomes; uncertain outcomes go to reconciliation (status query before any retry) | G | 1 | v1 | 7 | – | – | Planned (M7) |
| REC-08 | Append-only audit trail | G | 1 | v1 | 7 | – | – | Planned (M7) |
| REC-09 | Recovery restricted to the simulated environment | G | 1 | v1 | 7 | – | – | Planned (M7) |

## Part H: benchmark

| ID | Requirement | Spec | Tier | Release | M | Implementation | Evidence | Status |
|---|---|---|---|---|---|---|---|---|
| BENCH-01 | Arm A: scripted operator following the runbooks | H1 | 1 | v1 | 5 | – | – | Planned (M5) |
| BENCH-02 | Arm A: optional real human timing study (counterbalanced; real participants only) | H1 | 1 | v2 | – | – | – | Planned (v2) |
| BENCH-03 | Arm B: deterministic rules correlation (fingerprints, correlation-ID joins, error signatures, recent-change rule) | H1 | 1 | v1 | 5 | – | – | Planned (M5) |
| BENCH-04 | Arm C: B's evidence plus the AI investigator | H1 | 1 | v1 | 9 | – | – | Planned (M9) |
| BENCH-05 | At least 60 labelled incidents from the Part C scenarios, with varied timing, noise and compound cases | H2 | 1 | v1 | 9 | – | – | Planned (M9) |
| BENCH-06 | Dev / validation / held-out / stress splits grouped against leakage; ground truth from scenarios; versions and checksums | H2 | 1 | v1 | 9 | – | – | Planned (M9) |
| BENCH-07 | `benchmarks/thresholds.yaml` and `docs/hypotheses.md` committed before any arm or investigator code (moved to M3, ADR-0002) | H3 | 1 | v1 | 3 | – | – | Planned (M3) |
| BENCH-08 | Metrics with counts and denominators: top-1/top-3 root cause, citations, abstention, coverage, wrong recovery proposals, time to diagnosis and recovery, affected members, tool calls, tokens and cost | H4 | 1 | v1 | 9 | – | – | Planned (M9) |
| BENCH-09 | Per-scenario breakdown, where B beats or equals C, uncertainty estimates where justified | H4 | 1 | v1 | 9 | – | – | Planned (M9) |
| BENCH-10 | `make bench ARM=… SPLIT=… PROVIDER=… BUDGET=…` (plus a `.ps1` twin) and a compare command | H5 | 1 | v1 | 9 | – | – | Planned (M9) |
| BENCH-11 | JSON and Markdown reports; export in the Eval Harness format | H5 | 1 | v1 | 9 | – | – | Planned (M9) |
| BENCH-12 | Live runs only with a key and an approved budget; otherwise NOT RUN | H5 | 1 | v1 | 9 | – | – | Planned (M9) |
| BENCH-13 | Failure analysis (data, telemetry gap, retrieval, model, tool, rule, infrastructure); failing cases join the regression suite | H5 | 1 | v1 | 9 | – | – | Planned (M9) |
| BENCH-14 | No tuning on held-out data (freeze file with checksums) | H5 | 1 | v1 | 9 | – | – | Planned (M9) |
| BENCH-15 | Register Stage 10 in eval-harness's `PROJECTS` allowlist (a separate, reviewed eval-harness PR) | 0.4, continuity | 4 | v2 | – | – | – | Planned (v2) |

## Part I: security

| ID | Requirement | Spec | Tier | Release | M | Implementation | Evidence | Status |
|---|---|---|---|---|---|---|---|---|
| SEC-01 | Local auth with roles (operator, incident_commander, approver, auditor, admin), server sessions, CSRF, object-level authorization | I | 2 | v1 | 8 | – | – | Planned (M8) |
| SEC-02 | Login and API rate limits | I | 2 | v2 | 12 | – | – | Planned (v2) |
| SEC-03 | Secrets only from env; redaction in logs and traces tested; payloads minimized before model calls | I | 2 | v1 | 4, 6 | `app/preflight.py` reads env only (M1 part) | `tests/test_preflight.py` | Planned (M4) |
| SEC-04 | Signed webhooks with replay protection (timestamp plus nonce) | I | 2 | v2 | 10 | – | – | Planned (v2) |
| SEC-05 | SSRF protection: no model-selected URLs; allowlisted destinations only | I | 2 | v1 | 6 | – | – | Planned (M6) |
| SEC-06 | Injection tests: log/event injection (M6), approval tampering and approval-link replay (M7) | I | 2 | v1 | 6, 7 | – | – | Planned (M6) |
| SEC-07 | Injection test: alert-storm cost exhaustion | I | 2 | v2 | 10 | – | – | Planned (v2) |
| SEC-08 | Threat model: draft (trust boundaries, risks, controls, residual risks) | I | 2 | v1 | 6–8 | – | – | Planned (M6) |
| SEC-09 | Threat model: full, plus NIST AI RMF and OWASP (ASVS, LLM/agentic) mapping to evidence; no compliance claims | I | 2 | v2 | 12 | – | – | Planned (v2) |
| SEC-10 | `SECURITY.md` with a threat summary and the OWASP LLM Top 10 mapping (portfolio standard) | CLAUDE.md §18 | 2 | v1 | 8 | – | – | Planned (M8) |

## Part J: tests

| ID | Requirement | Spec | Tier | Release | M | Implementation | Evidence | Status |
|---|---|---|---|---|---|---|---|---|
| TEST-01 | Unit tests: rules engine, idempotency, approval hash, redaction, schema compatibility | J | 1 | v1 | 2–7 | – | – | Planned (M2) |
| TEST-02 | Integration with real Kafka and Postgres: publish/consume, duplicates, crash/restart, DLQ, retry topics, outbox, trace propagation, rebalance, lag | J | 1 | v1 | 2, 4, 7 | `tests/required_markers.py` (`kafka`, `postgres` markers; skips fail under REQUIRE_MARKERS); so far: publish/consume, outbox relay crash/restart, duplicates, Kafka outage, trace headers (`tests/test_relay_kafka.py`); still to come: consumer-side duplicates, DLQ and retry topics, rebalance (M2 PR-B2, PR-C), OpenTelemetry propagation (M4) | `tests/test_required_markers.py` | Planned (M2) |
| TEST-03 | Automation tests: dedupe and grouping, idempotent incident creation, kill switch | J | 2 | v1 | 8 | – | – | Planned (M8) |
| TEST-04 | Automation tests: storm limits, n8n webhook signature and callback | J | 2 | v2 | 10 | – | – | Planned (v2) |
| TEST-05 | Recovery tests: approval invalidation, replay idempotency, partial failure, uncertain → reconciliation, no duplicate credits (incl. concurrent replays) | J | 1 | v1 | 7 | – | – | Planned (M7) |
| TEST-06 | AI harness tests on the mock: every stop condition, malformed tool args, injection in logs, missing telemetry, insufficient evidence | J | 1 | v1 | 6 | – | – | Planned (M6) |
| TEST-07 | Playwright: alert → auto-incident → investigation with citations → approval by a different user → replay → verified recovery → follow-up list | J | 1 | v1 | 8 | – | – | Planned (M8) |
| TEST-08 | `make test` and `scripts\test.ps1` run everything offline | J | 1 | v1 | 1 | `scripts\test.ps1`, `Makefile` | `docs/verification-log.md` M1 | Implemented and verified |

## Part K: deployment and CI

| ID | Requirement | Spec | Tier | Release | M | Implementation | Evidence | Status |
|---|---|---|---|---|---|---|---|---|
| DEL-01 | Compose profiles `core`, `observability`, `full`; migrations, seeds, scenario trigger/reset, health and readiness, graceful shutdown | K | 1 | v1 | 2–4 | Part: `docker-compose.yml` profile `core` (health checks, `--wait`), `app/db/bootstrap.py`, `app/db/migrate.py`, ledger `/healthz` `/readyz`; still to come: posting and relay services, seeds (M2), `observability` (M4), triggers and resets (M3) | – | Planned (M2) |
| DEL-02 | Compose profile `automation` (n8n, mock Slack/Jira) | K | 2 | v2 | 10 | – | – | Planned (v2) |
| DEL-03 | GitHub Actions CI: ruff, mypy, pytest with Kafka and Postgres services, migration check, gitleaks, pip-audit, container scan, SBOM, Playwright, least-privilege permissions, no paid key | K | 2 | v1 | 2–13 | Part: `.github/workflows/ci.yml` (checks, integration, migrations, secrets, audit; `contents: read`; SHA-pinned actions; no secret stored); still to come: container scan and SBOM (M13 slice), Playwright (M8) | – | Planned (M2) |
| DEL-04 | Local CI equivalent with the same pinned tools | K, Stage 9 | 2 | v1 | 1 | `scripts\ci_local.ps1` (M1 jobs: checks, audit, secrets) | `docs/verification-log.md` M1 | Implemented and verified |
| DEL-05 | Pre-commit: gitleaks (pinned image), private-key block, ruff | 0.3, §9 | 1 | v1 | 1 | `.pre-commit-config.yaml` | `docs/verification-log.md` M1 | Implemented and verified |
| DEL-06 | lychee link check in CI | CLAUDE.md §18 | 2 | v1 | 13 | – | – | Planned (M13) |
| DEL-07 | Schema-registry compatibility rules as a release gate | K | 1 | v1 | 2 | Part: `BACKWARD_TRANSITIVE` enforced by the registry (`tests/test_kafka_stack.py::test_the_registry_enforces_backward_transitive_compatibility`); the CI gate over committed schemas comes in the third M2 PR | – | Planned (M2) |
| DEL-08 | Cloud options (2–3) with monthly costs from current official pricing, and teardown steps | K | 2 | v2 | 13 | – | – | Planned (v2) |
| DEL-09 | Deploy only after the owner approves the option and budget; public demo mode (synthetic, mock AI or capped live, rate-limited scenario button, auto reset, no shared admin) | K | 2 | v2 | 13 | – | – | Planned (v2) |
| DEL-10 | Verify the live URL with Playwright before adding the link | K | 2 | v2 | 13 | – | – | Planned (v2) |
| DEL-11 | Terraform for the chosen option, validated locally (pinned image), never applied without approval | K | 2 | v2 | 13 | – | – | Planned (v2) |
| DEL-12 | Application and migration rollback docs | K | 2 | v2 | 13 | – | – | Planned (v2) |
| DEL-13 | `Dockerfile` + `.dockerignore`; `CHANGELOG.md`; `CONTRIBUTING.md` (portfolio repo standard) | CLAUDE.md §5 | 1 | v1 | 1–13 | `.dockerignore`, `CHANGELOG.md` (M1) | `tests/test_secrets_hygiene.py` | Planned (M2) |

## Part L: drills, SLOs, handover

| ID | Requirement | Spec | Tier | Release | M | Implementation | Evidence | Status |
|---|---|---|---|---|---|---|---|---|
| OPS-01 | On-call runbooks, one per alert, versioned (also the source for arm A and `search_runbooks`) | L, D, E2 | 1 | v1 | 4–5 | – | – | Planned (M4) |
| OPS-02 | SLOs proposed and kept separate from measured results | L | 3 | v2 | 14 | – | – | Planned (v2) |
| OPS-03 | Game days with actual results: ledger outage, credential expiry, poison flood, consumer crash, model outage, n8n down, alert storm, database restore (timed) | L | 3 | v2 | 14 | – | – | Planned (v2) |
| OPS-04 | One full post-incident review from an executed drill | L | 3 | v2 | 14 | – | – | Planned (v2) |
| OPS-05 | Handover: ownership and escalation matrix, support handover, agent and approver UAT scripts, training guide, open-issue register | L | 3 | v2 | 15 | – | – | Planned (v2) |

## Part M: MCP reuse

| ID | Requirement | Spec | Tier | Release | M | Implementation | Evidence | Status |
|---|---|---|---|---|---|---|---|---|
| MCP-01 | Read-only MCP tools (`get_incident`, `get_timeline`, `search_runbooks`) with Stage 7 conventions: role decides tools, tenants isolated, every call audited | M | 2 | v2 | 11 | – | – | Planned (v2) |
| MCP-02 | No recovery tools over MCP; auth tests | M | 2 | v2 | 11 | – | – | Planned (v2) |

## Part N: personal proficiency

| ID | Requirement | Spec | Tier | Release | M | Implementation | Evidence | Status |
|---|---|---|---|---|---|---|---|---|
| PERS-01 | Each milestone: what changed, why, how to verify, failure modes, one exercise | N | 1 | v1 | all | `docs/session-handoff.md` (M1 notes) | `docs/session-handoff.md` | Implemented and verified |
| PERS-02 | The eleven exercises, scheduled at the milestone where each makes sense (`docs/implementation-plan.md` §5) | N | 1 | v1 | all | `docs/implementation-plan.md` | – | Planned (M2) |

## Part O: portfolio

| ID | Requirement | Spec | Tier | Release | M | Implementation | Evidence | Status |
|---|---|---|---|---|---|---|---|---|
| PORT-01 | Project card: real output example labelled "real output, synthetic data"; exactly three headline metrics with denominators, runs, held-out, date and version | O | 4 | v1 | 16 | – | – | Planned (M16) |
| PORT-02 | Case study: problem, Stage 9 link, architecture and event semantics, automation flow, results incl. where rules beat AI, limitations | O | 4 | v1 | 16 | – | – | Planned (M16) |
| PORT-03 | Case study: drills section | O | 4 | v2 | 16 | – | – | Planned (v2) |
| PORT-04 | README in house style (CLAUDE.md §18 order, "Design at scale", business value as projection) | O, §17–18 | 4 | v1 | 16 | `README.md` (M1: what exists today only) | – | Planned (M16) |
| PORT-05 | Demo video: Playwright-recorded flow; first-person narration script the owner can record; generated voice labelled "AI-narrated" (ADR-0004); captions; silent captioned version; `docs/VIDEO_SCRIPT.md` | O, §17 | 4 | v1 | 16 | – | – | Planned (M16) |
| PORT-06 | Site integration as PRs the owner approves: stage list, "How I work" table, OG image, stills | O | 4 | v1 | 16 | – | – | Planned (M16) |
| PORT-07 | Portfolio coverage map update (event-driven, observability, AIOps, automation, live deployment) | O | 4 | v2 | 16 | – | – | Planned (v2) |
| PORT-08 | Drafts: one Notes post, a LinkedIn post (two variants), résumé bullets; verified numbers only; no employer metrics | O | 4 | v2 | 16 | – | – | Planned (v2) |
| PORT-09 | Live app link on the card only when verified | O | 4 | v2 | 16 | – | – | Planned (v2) |
| PORT-10 | Every number shown traces to a stored result file (checked by a script) | O, rule 3 | 4 | v1 | 16 | – | – | Planned (M16) |
| PORT-11 | GitHub repo card: one-sentence About, topics, website link | CLAUDE.md §17 | 4 | v1 | 16 | – | – | Planned (M16) |

## Part P: milestones (cross-cutting)

| ID | Requirement | Spec | Tier | Release | M | Implementation | Evidence | Status |
|---|---|---|---|---|---|---|---|---|
| VER-01 | Clean-install verification: fresh clone → README quickstart → offline tests, benchmark and Playwright pass (v1 scope) | P (M17) | 4 | v1 | 17 | – | – | Planned (M17) |
| VER-02 | Clean-install verification for the v2 scope | P (M17) | 4 | v2 | 17 | – | – | Planned (v2) |

## Purpose lenses (owner, Stage 9's `docs/project-purpose.md`, applied proportionately)

| ID | Requirement | Spec | Tier | Release | M | Implementation | Evidence | Status |
|---|---|---|---|---|---|---|---|---|
| PURP-01 | ADRs record options considered and what would change the decision | rule 8 | 1 | v1 | all | `docs/decisions.md` | `tests/test_repo_guidance.py::test_adrs_have_the_stage9_headings` | Implemented and verified |
| PURP-02 | `docs/real-system-swap-guide.md` for every mock or adapter | rule 8 | 1 | v1 | 2+ | – | – | Planned (M2) |
| PURP-03 | `docs/onboarding.md`, updated every milestone | rule 8 | 1 | v1 | all | `docs/onboarding.md` (M1) | `tests/test_repo_guidance.py::test_tracking_files_exist` | Implemented and verified |
| PURP-04 | Principal artifacts: technical strategy, scaling and limits, tech-debt register, TCO (estimates labelled) | rule 8 | 1 | v1 | 2+ | – | – | Planned (M2) |
| PURP-05 | One RFC per design-heavy milestone (2, 3, 6, 7, 9, 10) | rule 2, rule 8 | 1 | v1 | 2+ | – | – | Planned (M2) |
| PURP-06 | Executive brief at the end of each phase | rule 8 | 1 | v1 | 3, 9, 17 | – | – | Planned (M3) |
| PURP-07 | `docs/role-coverage-map.md`: roles exercised, with evidence only | rule 8 | 1 | v1 | all | `docs/role-coverage-map.md` | `tests/test_repo_guidance.py::test_role_map_claims_nothing_without_evidence` | Implemented and verified |
| PURP-08 | `docs/fde-tool-map.md` and `docs/tool-access-matrix.md` when tools change | rule 8 | 1 | v1 | 2+ | – | – | Planned (M2) |
