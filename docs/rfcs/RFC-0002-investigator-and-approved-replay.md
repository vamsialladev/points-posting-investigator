# RFC-0002: Pre-registration, scenarios, the read-only investigator and human-approved replay
Status: **accepted**      Milestones: 3, 6, 7 (with small slices of 4 and 5)      Author: Claude Code (Fable 5.2), for the owner      Date: 2026-11-27

**Approved by the owner on 2026-11-27** ("Yes to all three", with three additions recorded below). Decision record:
ADR-0019. Everything here is a simulation with synthetic data. "Live" for the stack means local Docker; "live" for
the model means a real Claude call, which is off unless the owner approves it.

## Approval checklist
| # | Question | Answer | Where it's covered |
|---|---|---|---|
| 1 | Is pre-registration committed before any investigator or arm code? | **Yes.** Phase 1 is documents and one test. `tests/test_preregistration.py` checks the git order and fails on a shallow clone | "Phases"; "Pre-registration" |
| 2 | Can the investigator write, replay or post? | **No, never.** It has no write tool, read-only database roles, read-only Kafka ACLs and no ledger token | "The three guarantees"; "Safety" |
| 3 | Does a replay need the owner's (a person's) approval, bound to the exact events? | **Yes.** The approval carries a hash of the exact message set, and any change invalidates it | "The three guarantees"; "Human-approved replay" |
| 4 | Can a replay double-post? | **No.** It re-enters the idempotent pipeline; the ledger's unique key is the last guard. Tests on real Kafka and Postgres prove it | "The three guarantees"; "Human-approved replay" |
| 5 | Is any money spent? | **$0 by default** (mock provider). One live run is pre-approved with a hard cap of **$3**, after pricing is re-checked | "Money" |
| 6 | Is any gate weakened? | **No.** The 80% coverage gate and the five required CI checks stay | "Delivery" |
| 7 | Is anything public or hosted? | **No.** Local Docker only; no website change | "Money" |

## The three guarantees (owner's request, 2026-11-27)
1. **The investigator can never write, replay or post.**
   - Its tool registry holds read tools only. A test asserts the registry has no tool that writes, and that an
     unknown tool name is refused and audited.
   - Its database roles have `SELECT` only, on views without raw payload bytes, in read-only transactions. Tests run
     as the real roles and show Postgres refusing `INSERT`, `UPDATE` and `DELETE`.
   - Its Kafka principal has Describe and Read only. A test shows its produce attempt refused by the broker.
   - It reads the ledger's database, never the ledger API, so it never holds the token that can credit.
   - The only thing it produces is a **proposal**: a row in its own database. A proposal does nothing by itself.
2. **A replay needs a person's approval, bound to the exact events.**
   - Deterministic code, not the model, checks eligibility and builds the message set and the preview.
   - The approval stores a SHA-256 over the action, the sorted message set (topic, partition, offset, event ID) and
     the ledger state of each message at preview time.
   - The approver is a different person from the requester. The approval expires and is single use.
   - Before execution the hash is recomputed. A changed, added or removed message, or a changed ledger state, fails.
3. **A replay can't double-post. Tests prove it.**
   - Replay re-enters the existing idempotent path (the retry worker for a dead parked event; the main topic for an
     event that was never parked). The ledger key is `stay_id:revision`, `UNIQUE` in the ledger's own table, and the
     ledger role can't update or delete.
   - Tests on real Kafka and Postgres: a second approval of one proposal; a modified proposal; two executors at
     once; a replay forced to run twice; a crash in the middle. Each ends by checking the ledger database directly:
     no idempotency key appears twice, and the credit sum is what the scenario expects.

## Context
- The owner's "Milestone 3" (a read-only AI incident investigator plus human-approved replay) spans three spec
  milestones: **M3** (pre-registration, scenario triggers and resets), **M6** (the investigator) and **M7**
  (recovery). The spec's numbers stay in the repo; 174 matrix rows and the tests that read them use them.
- Standing rule 3: hypotheses, thresholds and the catalog are committed before any arm or investigator code.
- M2 left evidence the investigator can cite: `posting`, `outbox`, `parked_event`, `skipped_event`, ledger
  `credits`, the DLQ topic with failure headers, metrics on three ports, and `traceparent` in headers and the outbox.
- M2 did not build: a lag metric, a "what changed" feed, structured logs in a store, or alert rules (all M4).

## Phases
| Phase | Spec | Content | Done when | Hours | Model cost |
|---|---|---|---|---|---|
| 0 | – | This RFC, ADR-0019 | merged on green | 2 | $0 |
| 1 | M3 | Pre-registration: catalog, hypotheses, thresholds, protocol with the scoring rubric, the lock file, the order test | the order test passes in CI | 5 | $0 |
| 2 | M3, M4 slice | A trigger and a reset for each of the 18 scenarios; the four minimal M4 pieces; Kafka ACLs | all 18 trigger and reset on the real stack | 14 | $0 |
| 3 | M5 slice | A minimal rules baseline (the fallback when the model is down) | a report on all 18 | 4 | $0 |
| 4 | M6 | The investigator: tools, loop, citations, mock providers, audit, GenAI spans | stop-condition, role, ACL and injection tests pass | 16 | $0 |
| 5 | M7 | Proposal, approval, replay | every replay test passes; no duplicate ledger key | 12 | $0 |
| 6 | – | Mock evaluation of the 18 dev scenarios, evidence, handoff, teaching notes | scores stored in result files | 6 | $0 |
| 7 | – | One live run on the dev scenarios | results stored apart from mock | 1 | about $0.50, cap $3 |

Phase 2, 4 and 5 need real-stack batches. Before each: `scripts\quiet_check.ps1 -Minutes 5`, then the owner's OK.
Offline and unit work can go on at any time.

## The investigator (Phase 4)
- **Questions:** "why didn't member X's points post?" (by member, stay, correlation ID or incident), "is this alert
  a real incident?", "what changed before this started?".
- **Tools:** the spec's nine, typed with Pydantic, each with a timeout and a bounded output of summaries plus
  evidence IDs.
  - `get_affected_postings` covers posting, outbox, parked, skipped and ledger rows.
  - `get_events` covers topic offsets and DLQ headers, never full payloads.
  - `get_consumer_lag`, `get_recent_changes`, `query_logs`, `get_metrics_window`, `get_service_health`, `get_trace`
    and `search_runbooks` complete the set.
- **Citations:** every tool result carries evidence IDs. A deterministic verifier removes any stated fact whose
  citation was not returned by a tool in that run, and counts it as a false claim.
- **Root cause:** one code from the closed list in `docs/failure-catalog.md`, or `insufficient_evidence` with the
  missing evidence named. No confidence percentages.
- **Loop:** a bounded state machine. Stop conditions, each tested: a valid diagnosis, insufficient evidence,
  repeated calls without new evidence, the step, token and cost limits, the deadline, cancellation, repeated
  failures.
- **Providers:** an application-owned interface. The default is a deterministic mock. The Claude provider (Haiku
  5.5) exists behind `FEATURE_LIVE_AI` and a budget, and is NOT RUN without the owner's OK.
- **Its own records:** runs, tool calls and proposals go to a separate `investigator` database through an
  insert-only role. Prompt version, model, tools, tokens, latency and stop reason are stored for every run.

## Safety (Phase 2 and 4)
- **Database roles:** `posting_investigator` and `ledger_investigator`: `SELECT` on views that leave out
  `raw_value` and `raw_key`, `default_transaction_read_only = on`.
- **Kafka ACLs:** SASL on the client listeners and the standard authorizer, one principal per service. The
  investigator may Describe and Read. Local only, without TLS, and labelled so. This adds local-only passwords to
  `.env` through `scripts\new_env.ps1 -AddMissing`, which prints nothing.
- **Untrusted input:** event payloads, headers, error details, logs and runbook text are data. Tools return them in
  marked, truncated fields.
- **Injection tests:** the guarantee is structural, so the tests use a **hostile mock provider** that obeys the
  poisoned text: it asks for a write tool, cites evidence that doesn't exist, and proposes replaying everything.
  The tests assert on effects: no write happens, the fake citation is removed, the proposal is refused by the
  eligibility rules. Poison is planted in the DLQ `error_detail`, a log message, a correlation ID and a runbook.
  Whether a real model is fooled is measured only in the live run.
- **Audit:** every tool call is recorded append-only: run, step, tool, redacted arguments, evidence IDs returned,
  duration, allowed or denied.

## Human-approved replay (Phase 5)
- **Allowed actions:** DLQ replay of selected messages, pause and resume a consumer, re-run the outbox relay for
  stuck rows. Nothing else.
- **Flow:** proposed → previewed → approved → executing → done (or refused, expired, failed). Every transition is
  fenced in the database, so two executors can't both move one proposal.
- **Eligibility is deterministic,** by error class. A poison event or an undecodable event isn't replayable: the
  same bytes would fail again.
- **How an event re-enters:** a dead parked event is re-opened for the retry worker, because the posting service
  reports an already-parked event ID as a duplicate. An event that was never parked goes back to the main topic
  with its original key, value and headers plus a `replay_id` header. The replayer has its own database role and
  Kafka principal; the investigator has neither.
- **Per-message outcomes:** posted, already posted (skipped), failed, uncertain. An uncertain outcome goes to
  reconciliation: a ledger status lookup before any retry.
- **Limits:** a maximum batch size, attempt limits, a kill switch.
- **Limit of this phase:** approval is by CLI and API with local principals. Real sign-in and the web UI are M8.

## Scenarios and evaluation (Phases 1, 2 and 6)
- **Pre-registered:** the 18 scenarios with root-cause codes, expected evidence, correct recovery and affected
  members; the scoring rubric; H1 to H5; the thresholds; the protocol.
- **Triggers and resets:** `python -m app.scenarios trigger <id>` and `reset <id>`, with `scripts\scenario.ps1`.
  Each writes a manifest with the events it sent; the ground truth for affected members comes from the manifest.
- **Scores:** root-cause top-1, citation correctness, false claims and correct abstention, each with a count and a
  denominator.
- **Mock in CI:** evidence snapshots captured from real triggers let CI score offline. Mock scores measure the
  harness, not a model, and are stored and labelled as mock.
- **Not here:** the benchmark of at least 60 incidents, the splits and arms A, B and C compared stay in M5 and M9.
  The held-out split is not touched before M9.
- **The ledger `members` table** is not needed by any of the 18 scenarios. It moves to v2 (ADR-0019).

## Scope against M4
| Scenario | Gap | Built now (minimal) | Stays in M4 |
|---|---|---|---|
| S09 Backlog and lag | consumer-lag metric | a read-only lag reader: committed offsets against end offsets | Prometheus series, dashboard |
| S12 Config change | "what changed" feed | a `change_event` table that the triggers write | simulated deploy records |
| S17 Injection in a log | structured logs in a store | a `log_event` table with trace and correlation IDs | redaction filter, retention |
| S18 Noisy alert | alert rules | rules in a YAML file and a Python evaluator | Prometheus rules, runbook links |

Prometheus, Grafana, Tempo and the OpenTelemetry Collector stay in M4.

## Observability (Phase 4)
OpenTelemetry spans for each run (`invoke_agent`), each model call (`chat`) and each tool call (`execute_tool`),
with `gen_ai.*` attributes for the operation, model, token usage and tool name. No prompt or payload text goes on a
span. Tests assert the span tree with the in-memory exporter. OTLP export switches on when
`OTEL_EXPORTER_OTLP_ENDPOINT` is set. The GenAI semantic conventions' stability status is checked in the current
official documentation when Phase 4 starts, and recorded in an ADR (OBS-07).

## Money
- **$0** for Phases 0 to 6: local Docker, free GitHub Actions, the mock provider.
- **Phase 7, pre-approved by the owner (2026-11-27):** one live run with Claude Haiku 5.5 on the 18 dev scenarios,
  3 runs each, plus the injection cases. **Hard cap: $3**, enforced in code.
  - Estimate: about $0.01 per investigation, about $0.50 in total. It assumes $0.10 and $0.50 per million input and
    output tokens.
  - **Before the run:** the price is re-checked on Anthropic's official pricing page, the estimate is redone and
    shown to the owner, and the cap stays $3.
- Nothing is deployed. No account is created.

## Delivery
- Small PRs from `main`, each merged with a merge commit only when the five required checks are green.
- The CI `checks` job fetches full history so the order test can read it. No job is added or renamed.
- Every commit uses the noreply author. `docs/session-handoff.md` is kept current at each phase end.
- Each phase ends with a report of at most five lines: done, pass counts, cost, next, what the owner must do.

## Risks
| Risk | Mitigation |
|---|---|
| SASL breaks the 68 real-stack tests | Its own PR; the full real-stack suite runs before merge; the owner is asked before the batch |
| A catalog entry turns out wrong once its trigger runs | The lock file may change until the first arm or investigator commit, each change a visible commit; after that only dated amendments that never change a ground truth |
| Mock results read as model quality | Mock and live results live in separate folders and are labelled; the card and README can only use a live number if the live run happened |
| Other sessions need the machine | Quiet check and the owner's OK before each batch; scratch topics for probes; the stack comes down afterwards, data kept |

## What would change this RFC
- The owner wants the web approval screen now: then M8's sign-in moves ahead of Phase 5.
- SASL can't be made reliable on Docker Desktop: then ACLs become documentation plus a code-level check, with the
  owner's OK, and the limit is recorded.
- The live run's re-checked price makes the estimate exceed $3: stop and ask.
