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
- **Ledger entry IDs are unique but can skip numbers.** A replay, or the loser of a race, still draws a sequence value
  before `ON CONFLICT` discards its row. So after `L-0000001` and a replay, the next credit is `L-0000003`
  (`tests/test_ledger_postgres.py::test_entry_ids_are_unique_but_not_gapless`). Nothing may assume gapless IDs. A
  real ledger that must be gapless would number entries in a separate, locked step.

## Added in Milestone 2, PR-B1: the outbox relay (2026-11-22)
- **`points.posted` is at least once, not exactly once.** A relay that dies after publishing and before marking, or one
  so slow that its lease runs out, means a second relay publishes the row again. Readers must dedupe on `event_id`.
  The duplicate case is tested (`test_a_crash_after_publish_before_marking_publishes_twice_and_readers_dedupe`).
- **One message per member is in flight at a time.** It keeps per-member order across relays, and caps a single
  member's throughput at one message per relay cycle. Fine for sparse loyalty postings; a hot key would need
  partition leases (ADR-0014, option 3).
- **A row that fails transiently forever never goes `dead`.** Transient failures aren't counted, by design, so an
  outage can't dead-letter good messages. Such a row shows up as outbox lag; the alert on that is written in M4.
- **Dead rows stay dead.** Nothing replays them yet. Replay is M7: proposed, approved by someone other than the
  requester, and audited.
- **The relay's stats query scans the outbox every cycle.** That's fine at demo size. A real outbox needs a retention
  job for published rows.
- **`/metrics` has no authentication.** It binds 127.0.0.1 on the host. Prometheus, dashboards and alert rules come
  in M4.
- **librdkafka logs a connection failure every 2 s while Kafka is down.** It's noisy but expected; the relay itself
  logs one warning per failed cycle.
- **The Kafka-outage test takes about 100 s.** CI runs it once; the 10-run tallies are from the owner's machine
  (`docs/evidence/m2-pr-b1-repeat-runs-first.md`, `docs/evidence/m2-pr-b1-repeat-runs-outage.md`).

## Added in Milestone 2, PR-B2a: the producer and the posting service (2026-11-23)
- **For a moment, the ledger can hold a credit with no posting row.** The ledger is credited before the posting
  transaction (it's a separate system). A crash in between leaves the credit until the event is redelivered. The
  retry gets the same entry back (the key is the stay) and writes the rows. It can never hold two credits.
- **A database failure still blocks its partition.** Parking needs the database, so on a database failure the consumer
  seeks back and retries the same message. Since B2b, every other failure parks instead (ADR-0016).
- **Corrections (revision > 1) are dead-lettered as `unsupported_revision`** until PR-C builds the difference rule.
- **Dead letters are at least once.** The DLQ message is published before the offset commit. A crash between the two
  publishes it again; DLQ readers should dedupe on `event_id` plus the original offset.
- **One posting service instance** runs in the stack. Two in one consumer group (a rebalance) aren't tested yet:
  that's TEST-02, in PR-C.
- **The stack's smoke tests leave rows behind** (member `GR-09998` / `GR-09999`) in the stack's own databases.
  `scripts\stack.ps1 reset` clears them.

## Added in Milestone 2, PR-B2b: parking and the retry worker (2026-11-26)
- **One stuck event holds back its member.** Later events of that member park behind it until it posts or is
  dead-lettered. This keeps per-member order, by design (ADR-0016). Other members never wait.
- **A transient failure never dead-letters.** During a long ledger outage an event can wait indefinitely; it shows as
  `posting_parked_oldest_age_seconds`. The alert on it is M4.
- **Parked and dead events stay in the table.** There's no retention job yet, and dead events are never replayed
  automatically (replay is M7, with approval).
- **The DLQ copy is published before the event is marked `dead`.** A crash between the two publishes it again on the
  next attempt. DLQ readers should dedupe on `event_id` plus the original offset.
- **A stack created before B2b keeps three unused `.retry.N` topics** until the Kafka container is recreated.
- **Transient failures in the tests are injected** for chosen stays, in front of the real ledger client
  (`FlakyLedger`). Permanent failures are real: a stay over the ledger's points limit gets the ledger's own 422.
