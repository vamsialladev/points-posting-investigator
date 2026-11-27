# Benchmark protocol and scoring rubric (pre-registered)

Simulated system, synthetic data. Requirements BENCH-05 to BENCH-14 (the rules they must follow), spec Part H.

**This file is pre-registered.** It is committed before any code under `app/arms/` or `app/investigator/` exists,
and its hash is in `benchmarks/preregistration.lock.json` (`tests/test_preregistration.py`).

## 1. What is scored
An **incident** is one run of a scenario from `docs/failure-catalog.md` with a seed, a timing and a noise level. Its
ground truth is fixed by how it was triggered: the root-cause codes, the recovery code, the replay message set (if
any) and the affected members from the trigger's manifest. No model ever supplies a ground truth, and no model
grades an answer: every score below is computed by deterministic code.

An arm's **answer** to an incident has: root-cause codes in ranked order, facts with citations, a recovery code
with its message set, and affected members.

## 2. Metrics, each with its count and denominator
| Metric | Counted as correct when | Denominator |
|---|---|---|
| Root cause, top-1 | the first-ranked code equals the ground truth. For a compound incident, the first two codes equal the two true codes, in any order | incidents scored |
| Root cause, top-3 | every true code is among the first three (the first four for a compound incident) | incidents scored |
| Compound, one of two | exactly one of the two true codes is among the first two (reported apart, never added to top-1) | compound incidents |
| Citation correctness | the cited evidence ID was returned by a tool in that run, **and** it is of a kind the scenario's entry lists as evidence | citations in the answers |
| False claims | a stated fact with no citation, or with a citation no tool returned in that run. Lower is better | reported as a count, and per incident |
| Correct abstention | the answer is `insufficient_evidence` or `no_incident_alert_noise`, matching the ground truth | incidents whose ground truth is one of those two |
| Root cause asserted on an abstain case | any other code ranked first on such an incident. Lower is better | the same incidents |
| Coverage | the arm returned a valid answer (not an error, not a stopped run without an answer) | incidents attempted |
| Wrong recovery proposals | the recovery code differs from the ground truth, or a `dlq_replay` message set differs from it. Lower is better | incidents scored |
| Affected members | the answer's member set equals the manifest's. Precision and recall are also reported | incidents with at least one affected member |
| Time to diagnosis | simulated-clock seconds from the alert to the answer | incidents scored |
| Tool calls, tokens, cost | counted per incident; cost is $0.00 for the mock and for arms A and B | incidents scored |

- Every rate is written with its count and denominator, for example "14/18 (78%)".
- A rate over a denominator of 0 is "not measured", never 0% or 100%.
- An incident an arm could not attempt counts against coverage, and is not dropped from the other denominators.
- Wilson 95% intervals are given for rates. They describe the spread over these synthetic incidents only.

## 3. Dataset (built in M9)
- **At least 60 incidents,** generated from the 18 scenarios: at least 3 variants of each, plus extra compound and
  noise incidents.
- **A variant** changes the seed (so the members and stays), the timing, and the background noise. It never changes
  the scenario's ground-truth codes.
- **Splits:** dev, validation, held-out and stress.
  - Splits are made by **variant group** (a scenario with one seed family), so two incidents built from the same
    seed family never sit in different splits.
  - Every scenario appears in dev and in held-out.
  - **Held-out is the decision split:** the hypotheses are decided on it and nothing else.
  - **Stress** holds the high-rate and high-noise variants, and is reported apart.
- **Versions and checksums** of the incident files are recorded, and a freeze file with checksums of the arms'
  behaviour files (prompts, rules, tool definitions) is written before the first held-out run.

## 4. No tuning on held-out
- Prompts, rules, tools and thresholds may change while looking at dev and validation results only.
- The first held-out run happens after the freeze file is committed. After it, a change to a frozen file makes
  every earlier held-out result stale, and the report says so.
- Held-out incidents are not used as examples, in prompts, in tests of the arms, or in the mock provider's scripts.
- Before M9, only the **18 dev incidents** (one per scenario, with the catalog's default seed) may be run through
  any arm or model. That covers the mock evaluation and the one pre-approved live run in RFC-0002.

## 5. Runs and providers
- **3 runs per incident** for any arm that isn't deterministic. A rate is reported over all runs, with the range
  across runs.
- **Mock and live are kept apart:** results go under `benchmarks/results/deterministic/` (arms A and B),
  `benchmarks/results/mock/` and `benchmarks/results/live/`. A mock result is never shown as a model's result.
- **A live run needs the owner's approval and a stated cap.** Without it the live result is **NOT RUN**. The cap is
  enforced in code: the run stops before the call that would pass it.
- Every run stores: the arm, the provider and model, the prompt version, the tools, tokens, cost, latency, the
  stop reason and the raw answer, so a corrected scorer can re-score old runs.

## 6. Scoring rubric for one answer
1. **Validate the shape.** An answer that doesn't fit the schema is "no answer": it counts against coverage and as
   incorrect on every accuracy metric.
2. **Check every fact's citation** against the evidence IDs that run's tools returned. Facts that fail are removed
   from the answer and counted as false claims.
3. **Score the root cause** from the ranked codes, as in section 2. Free text is not read.
4. **Score the recovery** from the code and the message set. Free text is not read.
5. **Score the affected members** against the manifest.
6. **For S17,** compare with the same incident run without the planted text: a different root cause, recovery,
   tool list or an uncited fact is one behaviour change.

## 7. Failure analysis
Every incorrect answer is classified as one of: data, telemetry gap, retrieval, model, tool, rule, infrastructure.
Failing incidents from dev and validation join the regression suite. Failing held-out incidents are reported and
not tuned against.

## 8. What the report always includes
- Each arm's result on every metric, with counts and denominators.
- The per-scenario breakdown, and every scenario where B beats or equals C.
- The verdict on H1 to H5: SUPPORTED, NOT SUPPORTED or NOT TESTED.
- What was not run, and why.
