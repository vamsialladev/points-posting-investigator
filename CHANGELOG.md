# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Milestone 1:
  - the specification (`docs/MASTER-SPEC.md`) and the approved v1 / v2 plan
  - `CLAUDE.md` with the owner's standing rules, and `AGENTS.md`
  - the continuity review
  - fictional discovery and workflow documents
  - the requirements matrix and the tracking files
- `app/preflight.py`: reports every setting as set, missing or invalid format, per profile, and never prints a value.
- `app/env_leaks.py`: finds `.env` values in tracked files; reports NOT RUN when there is nothing to check.
- `tests/required_markers.py`: with `REQUIRE_MARKERS`, a skipped infrastructure test, or no such test at all, fails
  the run.
- `tests/test_env_template.py`: fails if `.env.example` ever holds a real-looking value (ADR-0009).
- Claude Code deny rules cover every file ending in `.env`, and keep `.env.example` readable (ADR-0009).
- `tests/test_secrets_hygiene.py` fails if any env-named file in the repo (say `.env.qa`) has no Read deny rule.
- Scripts: `scripts\test.ps1`, `scripts\ci_local.ps1`, `scripts\preflight.ps1`, `scripts\new_env.ps1`,
  `scripts\leaks.ps1`, `scripts\secrets_scan.ps1` (gitleaks from a pinned image).
- Milestone 2, PR-A (RFC-0001, ADR-0010 to ADR-0012):
  - the core Docker Compose stack (Kafka 4.4.0 in KRaft mode, Karapace 6.2.4, Postgres 16.15) and the six pipeline
    topics
  - `posting` and `ledger` databases with owner (no login) and runtime roles, Alembic migrations and a drift check
  - the ledger mock (`app/ledger/`): idempotent credits, status lookup, token expiry, rate limit, latency, a local-only
    control endpoint
  - the Avro schemas for `stay.checked_out` and `points.posted`
  - the first GitHub Actions workflow: checks, real-infrastructure tests, migrations, secrets, audit
  - `scripts\stack.ps1`, `scripts\test_integration.ps1`, `scripts\new_env.ps1 -AddMissing`
  - new settings `LEDGER_DB_PASSWORD` and `POSTING_DB_PASSWORD`
- Milestone 2, PR-B1: the outbox relay (ADR-0014):
  - migration `0002`: outbox delivery state (`status`, `next_attempt_at`, `claimed_by`, `lease_until`, `dead_at`,
    `trace_context`), with check constraints and indexes
  - `app/pipeline/relay.py`:
    - several relays, each claiming every member's oldest open row (`FOR UPDATE SKIP LOCKED` plus a lease)
    - at-least-once publishing with trace context in the headers
    - transient and permanent failure classes, and dead-lettering at max attempts
    - Prometheus metrics on `/metrics`
  - `app/pipeline/trace.py`: W3C trace-context helpers
  - the `posting_relay` database role and the `RELAY_DB_PASSWORD` setting; `posting_app` no longer updates the outbox
  - the `relay` service in the core compose stack
  - `scripts\repeat_tests.ps1`: runs a test N times and stores the tally
- Milestone 2, PR-B2a: the producer and the posting service (ADR-0015):
  - `app/pipeline/producer.py`: synthetic `stay.checked_out` events with `event_id`, `schema_version`,
    `correlation_id` and a W3C `traceparent` in the headers; keyed by member; idempotent producer
  - `app/pipeline/events.py`: validation, 10 points per room-rate dollar, and the ledger business key
    `stay_id:revision`
  - `app/pipeline/ledger_client.py`: credits, with the 409, 401, 429, 5xx and 4xx outcomes classified, and status
    lookups after a timeout
  - `app/pipeline/posting.py`:
    - one transaction for the posting row and its outbox row
    - the Kafka offset committed only after that transaction
    - seek-back retries
    - dead letters with the original bytes and failure headers
    - `/metrics`
  - the `posting` service in the core compose stack
- Milestone 2, PR-B2b: parking and the retry worker (ADR-0016):
  - migration `0003`: the `parked_event` table (original bytes, status, attempts, transient failures, lease), with
    check constraints; `posting_app` can't delete or rewrite a parked event
  - the posting service parks a failed event, and every later event of the same member, instead of blocking the
    partition
  - `app/pipeline/retry.py`:
    - each member's oldest parked event first (`FOR UPDATE SKIP LOCKED` plus a lease)
    - exponential backoff
    - permanent failures dead-lettered after 5 attempts with the original bytes; transient ones never
  - the `retry-worker` service in the core compose stack
  - the retry topics (`stay.checked_out.retry.1/2/3`) removed
  - a failed offset commit (after the database commit) is a warning plus the
    `posting_offset_commit_failures_total{error}` metric, and the consumer keeps going; the redelivery is a duplicate
  - Kafka's test-only `FAULTS` listener (`127.0.0.1:19093`) for the producer fault tests
  - `scripts\repeat_tests.ps1` keeps every run's full output, one line per test, and flags runs on a busy machine
    (not counted); `scripts\quiet_check.ps1` checks that CPU load is low before a batch

- Milestone 2, PR-C (ADR-0018):
  - corrections (RFC-0001 D10): a higher revision credits the signed difference from the stay's latest posted one;
    a stale revision is recorded in `skipped_event` (migration 0004) and not credited; a correction with no
    original is retried as `original_missing`, then dead-lettered
  - `app/pipeline/seed.py`: synthetic members and distinct stays in Stage 9's shapes, with seeded event IDs
  - `app/pipeline/loadgen.py`: rate-paced synthetic load with hard caps (200/s, 10,000 a run), corrections and
    duplicates mixed in
  - `app/pipeline/schema_check.py`: the schema gate (local structural check plus the registry), a step in CI
  - docs: `event-semantics.md`, `architecture.md`, `data-dictionary.md`, `scaling-and-limits.md`,
    `tech-debt-register.md`, `real-system-swap-guide.md`
- Milestone 3, Phase 1 (RFC-0002, ADR-0019): the pre-registration, committed before any arm or investigator code:
  - `docs/failure-catalog.md`: 18 scenarios with closed root-cause and recovery codes
  - `docs/hypotheses.md` (H1 to H5), `benchmarks/thresholds.yaml`, `docs/benchmark-protocol.md` with the scoring
    rubric
  - `benchmarks/preregistration.lock.json` and `scripts/prereg_lock.py`: any later edit is a visible commit
  - `tests/test_preregistration.py`: checks the lock, the thresholds against the document, and the git order; fails
    on a shallow clone
- Milestone 3, Phase 2, offline parts (RFC-0002):
  - `app/scenarios/`: the 18 scenarios' trigger and reset plans as deterministic data, and
    `python -m app.scenarios list|plan`. The executor that runs them comes next
  - `app/ops/lag.py`: consumer lag from committed offsets and watermarks, with a read-only reader
  - `ops/alert-rules.yaml` and `app/ops/alerts.py`: alert rules as data and a deterministic evaluator

### Changed
- CI's `checks` job fetches the full history, so the pre-registration order test can read it.
- The ledger `members` table moves to v2 (ADR-0019).

### Fixed
- `synthetic_events` could give two members the same stay ID, so the second stay was refused as a duplicate (PR-C).
- The checkout producer could lose an event silently: `send()` returned before Kafka answered, and `flush()` only
  checked the queue. Every send now has a delivery callback, and `flush()` raises `DeliveryFailed` for any error or
  missing report. The producer uses idempotence, `acks=all`, the gapless guarantee and a bounded delivery timeout
  (ADR-0017; incident `docs/incidents/2026-11-26-producer-silent-loss.md`). Found by a repeat run of the two-workers
  test (6 events posted that should have parked).
- Kafka advertises `127.0.0.1` instead of `localhost`. The template uses `127.0.0.1` for Kafka and the registry.
