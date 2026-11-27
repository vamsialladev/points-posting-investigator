# Incident: the checkout producer reported success for events Kafka never took (2026-11-26)

Simulated system, synthetic data, local stack. Found by Claude Code during M2 PR-B2b's repeat runs. Decisions:
ADR-0017. Evidence: `docs/verification-log.md`, M2 PR-B2b; logs in `docs/evidence/`.

## What happened
During the B2b repeat batch (100 runs), run 3 of `test_two_workers_never_claim_the_same_parked_event_and_each_posts_once`
failed:
- **Expected:** 60 events, with each member's first event made to fail once, so every event should park.
- **What the consumer did instead:**
  - 50 events parked
  - **6 events posted directly**
  - **4 events never arrived** within the 120 s limit

A posted-directly event in that test means a member's later event went through while no earlier event of that member
was parked. That's the ordering the parking design is there to prevent, so it was treated as a possible correctness
bug until proven otherwise.

## Impact
On the simulated stack, events the producer had "sent" could be missing from `stay.checked_out`, with nothing reporting
it. Then:
- **The lost event:** never posted, so the member is never credited for that stay.
- **The member's later events:** posted ahead of it, because the parking rule had nothing to park behind.

No real system or data was involved.

## Root cause
`CheckoutProducer.send()` attached **no delivery callback**, and `flush()` only checked how many messages were **still
queued**. A message Kafka refused, or that timed out, leaves the queue with an error report nobody read. So `flush()`
returned 0 and `send()` reported success.

On its own that's a silent-loss bug. Two things combined into the observed failure:
- **The broker side was degraded during the batch.** Other projects were loading the machine; the posting container
  logged consumer-group session timeouts ("Not coordinator"); and Karapace's write path was stuck (registrations timing
  out after 20 s) until restarted.
- **librdkafka's default `enable.gapless.guarantee=false`.** A failed message doesn't stop later messages to the same
  partition from being delivered. So a member's first event could be lost while their later ones arrived.

### Evidence
| Step | Result |
|---|---|
| The failing run's log | 50 PARKED + 6 POSTED, 4 never handled, no RETRY or DUPLICATE outcomes, and no consumer-group events in the test's own consumer |
| The same scenario, 8 rounds, on a healthy stack (diagnostic script with `diag_` databases) | 60/60 parked every round: the anomaly needs the degraded broker |
| The producer code | no `on_delivery`; `flush()` checks queued messages only |
| A deterministic proof on the real stack: send to a topic that doesn't exist | `send()` **returned normally** after 1.7 s; Kafka's verdict for the same topic: `_UNKNOWN_TOPIC` |

What isn't proven: the exact broker error that lost those 4 events in run 3. The test's topic is deleted afterwards,
and no delivery reports were recorded then, because the code didn't read them, which is the bug. The pattern matches
lost first events: 4 missing plus 6 posted, for example one member losing its first event and another losing its first
three.

## Fix (ADR-0017)
- **A delivery callback on every message.** `send()` and `flush()` raise `DeliveryFailed` for any event that was
  refused, timed out, never reported, or still queued after the flush timeout, and name each event.
- **Producer settings:** `enable.idempotence`, `acks=all`, **`enable.gapless.guarantee=true`** (a gap-causing failure
  fails the producer, so no later message of that partition gets past a lost one), `max.in.flight ≤ 5`, and
  `delivery.timeout.ms` bounding retries.
- **The tests' producer now uses the same settings,** so a test whose events weren't all delivered fails at the send,
  loudly, instead of producing a confusing result.

## How tests caught it, and how they now cover it
- **Caught by:** the 10-times repeat runs. A single run of the suite passed. This is why repeat runs are part of the
  definition of done (and why the first batch's failure logs were kept).
- **Unit tests** (`tests/test_producer_unit.py`): refused, timed out, never reported, still queued, a batch with some
  failures, a synchronous produce error, and the settings.
- **Real-stack tests** (`tests/test_producer_kafka.py`):
  - (a) a topic that doesn't exist → `DeliveryFailed` with `UNKNOWN_TOPIC`
  - (b) an unreachable broker → `DeliveryFailed` after the 3 s delivery timeout
  - (c) no duplicates and per-member order under producer retries. A fault proxy (`tests/kafka_proxy.py`) cuts
    connections just as the broker replies, so batches the broker already wrote are sent again.
  - (c) also has a **control**: without idempotence, the same fault produced **37 duplicates**, so the "0 duplicates"
    in (c) is idempotence at work.
- **The two-workers test** is rerun 10 times on the fixed code in the final repeat batch, on a quiet machine. Its
  result goes in the verification log; until then, this fix is proven by the producer tests, not by that rerun.

## What went well, and what didn't
- **Went well:** the anomaly was treated as a possible correctness bug, not a flaky test, and found from data. The
  repeat script now keeps unbuffered output, `faulthandler` traces and exit codes for any run that doesn't pass.
- **Didn't go well:**
  - The first repeat script kept no per-run output, so B1's outage run 6 and B2b's crash-after-parking run 6 left
    nothing to examine.
  - During the diagnosis, Claude Code edited code while a repeat batch was running, which voided 4 of that batch's runs
    (logged).
  - A probe wrote one non-Avro message to the stack's `points.posted` topic. It was later cleared when Kafka was
    recreated.

## Follow-ups
- **Karapace's health check only reads** (`GET /subjects`), so it stayed "healthy" while writes failed. A write probe
  belongs in the M4 alerts.
- **A fatal producer error** (a gap under the gapless guarantee) leaves the producer unusable. The caller must build a
  new one. That's documented in `DeliveryFailed`; the load generator (PR-C) should do it.
