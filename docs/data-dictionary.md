# Data dictionary (Milestone 2)

Simulated system, synthetic data. Shapes follow Stage 9 (`loyalty-support-modernization`): members `GR-#####`, stays
`BR-####` / `ML-####`, ledger entries `L-#######`, tenant `hg-demo`, 10 points per US dollar of room rate.

## `stay.checked_out` (Avro, `schemas/stay.checked_out.v1.avsc`)
| Field | Meaning |
|---|---|
| `event_id` | UUID; the event's identity. A resend keeps it |
| `occurred_at` | when the checkout happened (UTC, ms) |
| `tenant` | `hg-demo` |
| `property` | `beach-resort` or `mountain-lodge` |
| `stay_id` | `BR-####` or `ML-####`, matching the property |
| `member_number` | `GR-#####`; also the Kafka message key |
| `revision` | 1 for the original; higher for a correction (D10) |
| `check_in`, `check_out`, `nights` | dates, and nights = the difference |
| `room_rate_cents` | the only amount that earns points |
| `taxes_cents`, `fees_cents` | carried, never earn |
| `currency` | `USD` only |
| `correlation_id` | carried through every hop and log line |

## Posting database (`posting`)
| Table | One row per | Key columns |
|---|---|---|
| `posting` | posted stay revision | `event_id` (PK), `UNIQUE(stay_id, revision)`, `stay_points`, `credited_points` (the difference for a correction), `ledger_entry_id` |
| `outbox` | `points.posted` message to publish | `status` (pending, in_flight, published, dead), `message_key` (member), `payload`, `trace_context` |
| `parked_event` | event waiting for a retry | the original bytes, `status` (pending, in_flight, done, dead), `attempts`, `transient_failures`, `error_class` |
| `skipped_event` | stale revision, not credited | `event_id` (PK), `revision`, `latest_revision`, `reason` |

## Ledger database (`ledger`, the mock system of record)
| Table | One row per | Key columns |
|---|---|---|
| `credits` | credit | `entry_id` `L-#######`, `UNIQUE(idempotency_key)` = `stay_id:revision`, `request_hash`, `points` (negative only for a correction) |

## Mapping to Stage 9's `PostingQueueItem`
Stage 9 shows agents a posting queue item. This is where each of its fields comes from in Stage 10:

| Stage 9 field | Stage 10 source |
|---|---|
| `item_id` | the event's `event_id` (posting or parked row) |
| `member_number` | `member_number` |
| `stay_id` | `stay_id` |
| `points` | `posting.credited_points` (or, while waiting, the points the plan would credit) |
| `queued_at_utc` | `parked_event.parked_at`, or the event's `occurred_at` |
| `expected_post_at_utc` | `parked_event.next_attempt_at` while parked; not modelled for events in flight |
| `posts_entry_id` | `posting.ledger_entry_id` once posted |

The Stage 9 adapter that reads these is M11 (v2).
