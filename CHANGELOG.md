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
- Kafka advertises `127.0.0.1` instead of `localhost`. The template uses `127.0.0.1` for Kafka and the registry.
