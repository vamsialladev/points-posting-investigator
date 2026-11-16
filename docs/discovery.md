# Discovery: points-posting incidents (FICTIONAL)

> **Everything in this document is fictional.** The hotel group, the people, the interviews, the volumes and the costs
> are simulated for an independent portfolio project with synthetic data. No real company, employee or incident is
> described. Numbers marked "assumption" are inputs to be tested, not findings.

Spec Part A. The format follows Stage 0's discovery (`hotel-ai-discovery`) and Stage 9's discovery.

## 1. The problem in one paragraph
When a guest checks out, the property system sends a `stay.checked_out` event; a posting service computes the points
and credits the loyalty ledger. When that chain breaks, the guest's points don't arrive. Today the first sign is often
a member writing in about missing points: Stage 9's queue, where defect D24 ("the property never transmitted the
stay") and D06 (late postings after a property interface outage) start. By then the cause is hours or days old. The
on-call engineer reconstructs it by hand from logs and topics, replays messages with scripts, and nobody tells
loyalty operations which members were affected.

## 2. Stakeholders (simulated roles)
| Role | What they own | What they need from Stage 10 |
|---|---|---|
| Integration / platform engineers | Producer, posting service, outbox, Kafka topics | Event semantics that are documented and tested; safe replay instead of scripts |
| On-call SRE | Alerts, first response, recovery | One place with the timeline and the evidence; a bounded, approved recovery |
| Loyalty operations lead (Stage 9's users) | Member cases and points adjustments | The list of affected members and postings, and confirmation the ledger was fixed |
| Support supervisor | Member replies and escalations | To know a case is an incident, not a member error, before replying |
| Security | Access, secrets, audit, third-party data flows | Read-only AI, no secrets or member data sent to the model, approvals that can't be forged or replayed |
| Engineering manager | Delivery, cost, on-call load | Evidence that this shortens diagnosis without raising wrong recoveries; a cost cap |

## 3. Interview excerpts (FICTIONAL)
- **On-call SRE:** "The alert says lag is high. That's all it says. I open three dashboards, grep the posting
  service logs, then read the dead-letter topic with a console consumer. Half the time it's the ledger rate-limiting
  us, and I've seen that before."
- **Integration engineer:** "Our replay script replays everything in the DLQ. If some of those already posted after a
  retry, we rely on the ledger to dedupe. I think it does. I've never seen a test that proves it."
- **Loyalty operations lead:** "We find out from members. Then I ask engineering whether there was an outage, and the
  answer is usually 'maybe, which dates?'"
- **Support supervisor:** "If I knew a batch of stays from Mountain Lodge failed on the 3rd, I'd hold those replies
  instead of asking each member for a receipt."
- **Security:** "I don't want a model running replays. Reading logs is fine if it can't see card numbers or tokens,
  and log text can't make it do things."
- **Engineering manager:** "Show me it beats a good runbook and a few correlation rules. If the rules get us most of
  the way, I'd rather own rules."

## 4. Pain points, written as hypotheses to measure (not assume)
These discovery hypotheses (DH) feed the formal, pre-registered benchmark hypotheses in M3 (`docs/hypotheses.md`).
Until then they are expectations, not results.

| ID | Hypothesis | How it would be measured | Could be false because |
|---|---|---|---|
| DH1 | Most diagnosis time goes to gathering evidence, not reasoning about it | Time to diagnosis, arm A vs arm B (simulated clock) | Arm A's scripted operator may gather fast; the bottleneck may be judgment |
| DH2 | Deterministic correlation (fingerprints, correlation-ID joins, error signatures, recent changes) gets most single-cause incidents right | Arm B top-1 accuracy on single-cause scenarios | Many incidents may need reading free-text errors |
| DH3 | AI adds value mainly on compound, "what changed" and insufficient-evidence incidents | Arm C vs B per scenario | AI may add nothing measurable, or may overreach on uncertain cases |
| DH4 | Replaying the whole DLQ risks double credit without ledger idempotency | Duplicate-credit tests with and without the ledger's unique constraint (M2, M7) | The ledger may already dedupe every path |
| DH5 | Members affected are knowable from the telemetry within the incident window | Affected-member list vs ground truth (M8) | Some failures (schema break) may drop the member ID before it is logged |
| DH6 | Log-borne prompt injection is a real risk to an AI investigator | Injection scenario (FAIL-17): behaviour unchanged | The model may never act on it; that is still worth showing |

## 5. Success metrics (spec Part A)
| Metric | Definition (finalized in M3's protocol) | Better is |
|---|---|---|
| Time to diagnosis | Simulated minutes from the first alert to a stated root cause or "insufficient evidence" | Lower |
| Root-cause accuracy | Top-1 (and top-3) match with the scenario's ground truth, with counts and denominators | Higher |
| Wrong recovery proposals | Recommended actions that are not the scenario's correct recovery, or unsafe | Lower (must not rise with AI) |
| Members affected identified | Affected members found vs ground truth (precision and recall) | Higher |
| Time to correct points | Simulated minutes from diagnosis to the ledger reconciled for every affected posting | Lower |
| Duplicate credits | Ledger credits beyond one per event | Exactly zero |

## 6. Scope
- **In scope (v1):**
  - the synthetic pipeline and the 18 pre-registered failure scenarios
  - telemetry, alerts and runbooks
  - three investigation arms (manual runbook, rules, AI-assisted)
  - three recovery actions with human approval
  - the affected-member list
  - a benchmark and a demo
- **In scope (v2):**
  - n8n and ticket/notification mocks
  - the Stage 9 write-back adapter
  - MCP read-only tools
  - cloud deployment
  - drills and handover

## 7. Exclusions
- Loyalty adjustments, the legacy support benchmark, document AI and the classical-ML baseline. Stage 9 owns them
  (spec 0.4).
- Real hotel systems, real members, real messages and real money.
- Any action by the AI: it reads and recommends only.
- Exactly-once delivery across the system: not claimed.

## 8. Risks and RACI
| Risk | Mitigation |
|---|---|
| The scenarios restate the author's assumptions (the same author writes the catalog, the arms and the labels) | Pre-register the catalog, hypotheses and thresholds before any arm code (M3); include rules-are-enough and noise cases; report where AI didn't help |
| A wrong recovery double-credits points | Three layers: event-ID key, ledger check before replay, unique constraint in the ledger (M2, M7) |
| Log text steers the AI | Untrusted-input handling, read-only tools, effect-based injection tests (M6) |
| Model cost runs away in an alert storm | Per-incident and per-hour limits, daily budget, kill switch (M8); circuit breaker (v2) |
| Benchmark tuned on held-out | Split rules and a freeze file (M9) |

**RACI** (R = responsible, A = accountable, C = consulted, I = informed):

| Activity | Platform eng. | On-call SRE | Loyalty ops | Support sup. | Security | Eng. manager |
|---|---|---|---|---|---|---|
| Event schemas and the outbox | R/A | C | I | – | C | I |
| Alert rules and runbooks | C | R/A | I | I | C | I |
| Running an investigation | C | R | I | I | – | I |
| Approving a recovery | C | R (requester) | C | – | I | A (approver role) |
| Affected-member follow-up | I | C | R/A | R | – | I |
| AI usage, budget, data sent to the model | C | C | – | – | A | R |

## 9. What stays deterministic and what the AI does
| Stays deterministic (Python, tested) | AI does (read-only, cited, bounded) |
|---|---|
| Alert rules and thresholds | Correlate evidence across logs, traces, metrics, events and changes |
| Incident deduplication and grouping | Reconstruct the timeline |
| Replay eligibility and the preview | Separate observed facts (cited) from ranked hypotheses |
| Idempotency keys and the ledger's uniqueness | Say "insufficient evidence" and what to collect next |
| Authorization, approval binding, no self-approval | Recommend one recovery **from the allowed set**, with preconditions |
| Executing, verifying and reconciling recovery | Draft the incident report and the post-incident review |
| Budgets, limits and the kill switch | – |

The rules engine (arm B) is also the AI's fallback when the model is unavailable (spec E6).

## 10. Assumptions (FICTIONAL, to be replaced by measurements where the benchmark can)
| ID | Assumption | Used for |
|---|---|---|
| A1 | Two properties, one posting service, one ledger | Pipeline shape (M2) |
| A2 | Postings are keyed by the checkout event ID; one event credits one posting | Idempotency design (M2) |
| A3 | Members expect points within the waiting period Stage 9's policy defines | Clock-skew scenario (M3) |
| A4 | Incidents are rare enough that a daily model budget of a few dollars covers them | Budget defaults (`.env.example`); measured in M9 on the mock (tokens) and only with approval on live |
