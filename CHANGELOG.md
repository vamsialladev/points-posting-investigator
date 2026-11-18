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
