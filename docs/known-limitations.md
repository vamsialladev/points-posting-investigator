# Known limitations

Kept current at every milestone. Each line says what is limited, why, and what would change it.

## As of Milestone 1 (2026-11-16)
- **No product yet.** Only the setup, guidance, tracking, fictional discovery and the preflight command exist. Every
  pipeline, investigator, recovery and benchmark requirement is `Planned`.
- **The discovery is fictional.** Stakeholders, interview excerpts, volumes and costs are simulated and labelled.
  The pain points are hypotheses (DH1–DH6) to measure in the benchmark, not findings.
- **Preflight checks format, not validity.** It catches empty values, typos and wrong shapes (for example a key
  without `sk-ant-`). It can't tell whether a key is revoked or has spend left; a live smoke test (only with the
  owner's approval) does that.
- **Env-file variants are named, not globbed** (ADR-0009). That keeps `.env.example` readable, but a secret file
  with an unlisted variant (say `.env.qa`) is open to the Read tool. Shell readers still refuse it (`*.env.*`), and so
  does `Get-Content .env.example`, by choice: templates are read with the Read tool. Inside this repo, such a file
  fails `tests/test_secrets_hygiene.py` the next time the tests run, but not the moment it is created. Elsewhere under
  project1 nothing checks for it.
- **Every file ending in `.env` is blocked, secret or not** (ADR-0009). Stage 9's non-secret
  `config/environments/*.env` is an example; Stage 9 is read-only here anyway.
- **Shell deny rules match command text, not file access.** A reader not on the list, or a script that opens the file
  itself, isn't blocked. They guard against mistakes; they are not a sandbox.
- **The template test knows the secret shapes it was given** (`tests/test_env_template.py`): Anthropic, GitHub, AWS,
  Slack, private keys, URL passwords, JWTs, and random-looking letters-and-digits runs of 24 or more. A short real
  password typed into a non-secret name would pass it. gitleaks (pre-commit and history scan) is the second layer.
- **CI arrived with M2's first PR** (`.github/workflows/ci.yml`, merged 2026-11-18). PR #1 was merged before it
  existed, as a one-time exception the owner approved (verification log M1 #34).
- **`scripts\leaks.ps1` reports NOT RUN until `.env` exists.** That is by design (ADR-0007), not a fault.
- **The Makefile is untested on the owner's machine**, which has no `make`. The `scripts\*.ps1` twins are what ran.
- **No independent review.** The continuity review, the matrix and the discovery were written by Claude Code from
  the live site and the repos. Nobody else has reviewed them yet.
- **The coverage gate measures `app/` only.** Tests and scripts aren't measured.

## Added in Milestone 2, PR-A (2026-11-17)
- **One Kafka broker, replication factor 1.** That's fine for a local demo and wrong for production: one broker
  failing loses the log. It's labelled dev-only (RFC-0001 D1, D7).
- **The ledger mock doesn't check that a member exists.** It checks the `GR-#####` and `BR-` / `ML-####` shapes only.
  The members table comes with the seeds in M2 PR-C.
- **The ledger's control endpoint can break the ledger on purpose** (latency, rate limit, token expiry). It exists only
  with `LEDGER_CONTROL_ENABLED=true`, needs the token, and is always off with `PUBLIC_DEMO_MODE=true`.
- **`localhost` is rewritten to 127.0.0.1** for database connections (ADR-0012). A setup where `localhost` isn't the
  Docker host would need its real host name in `.env`.
- **Offline coverage leaves out the database code.** Bootstrap, migrations and the Postgres store are covered only by
  the infrastructure tests (`scripts\test_integration.ps1`, CI `integration`). The offline gate (80%) is met without
  them, at 82.82%.
- **The Karapace image is 1.72 GB.** The first `stack.ps1 up` downloads about 2.3 GB of images in total.
