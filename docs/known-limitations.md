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
- ~~Corrections (revision > 1) are dead-lettered as `unsupported_revision`.~~ Fixed in PR-C: corrections credit the
  difference (ADR-0018).
- **Dead letters are at least once.** The DLQ message is published before the offset commit. A crash between the two
  publishes it again; DLQ readers should dedupe on `event_id` plus the original offset.
- **One posting service instance** runs in the stack. A second consumer joining the group (a rebalance) is tested in
  PR-C (`test_a_second_consumer_joining_mid_stream_loses_nothing_and_credits_nothing_twice`).
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

## Added in Milestone 2, PR-C: corrections, seeds, the load generator, the schema gate (2026-11-27)
- **A correction that arrives before its original holds up that member.** The original parks behind it and posts only
  once the correction is dead-lettered (`original_missing`, after 5 attempts, a few seconds). The correction then
  needs a replay (M7). Tech debt #5.
- **The local schema check is structural:** flat records, exact logical types. The registry is the authority.
- **The load generator's hard caps** (200 events a second, 10,000 a run) refuse larger runs; they aren't measured
  throughput limits.
- **The ledger `members` table is deferred to M3** (ADR-0018, owner confirmed). The ledger doesn't validate members.
- **PR-C's real-stack tests** (corrections, original_missing, the skipped-event role, the rebalance) waited for a free
  machine; their results are in the verification log once run.

## Added in Milestone 3, Phase 1: the pre-registration (2026-11-27)
- **The catalog names commands that don't exist yet.** `python -m app.scenarios trigger|reset` is built in Phase 2 of
  RFC-0002. Until then FAIL-01 to FAIL-18 stay `Planned (M3)`.
- **The catalog can still change until the first arm or investigator commit.** A trigger may show an entry's
  evidence to be wrong. Each change must update the lock file, so it is a visible commit. After that point only
  dated amendments that never change a ground truth.
- **The evidence lines for S03 and S12 name `ledger_timeout_not_found`** from reading the code. The first real
  trigger run confirms the class or corrects the entry.
- **The thresholds are judgment, made before any arm ran.** A threshold that proves badly chosen is reported next to
  the result it produced, not changed.
- **The order test needs full git history.** It fails on a shallow clone, by design; CI's `checks` job now fetches
  everything.
- **The ledger `members` table moves to v2** (ADR-0019): no pre-registered scenario needs an unknown member.
- **The 18 scenarios have run on GitHub's runners, not on the owner's machine.** Six run in the required CI job and
  twelve in the "Scenario batch" workflow. A slower or busier machine can behave differently (verification log M3
  #7 shows one such case). The owner decided on 2026-11-28 that GitHub Actions is the source of truth for
  scenario runs and that no local batch will be run; so nothing here says how the scenarios behave on Windows
  with Docker Desktop.
- **Kafka logins travel without TLS** (SASL/PLAIN on loopback and the compose network). Local stack only
  (ADR-0021).
- **The controller listener has no login,** and its anonymous principal is a super user. It isn't published to the
  host; another container on the compose network could reach it.
- **The access list is only ever added to.** An entry removed from the code stays on a running broker until the
  Kafka container is recreated. A real-stack test compares the two lists.
- **Tests run as the broker's admin on scratch topics,** so most real-stack tests don't exercise the service
  identities' rights; `tests/test_kafka_acls_real.py` does.
- **Two passing runs were not enough to trust a scenario check.** S07's first assertion depended on timing and
  failed on the third run (verification log M3 Phase 2 #14c). Other batch checks have run three or four times;
  that is evidence of stability on GitHub's runners, not proof.
- **The posting service's retry line names the failure's type, not its cause.** "DatabaseFailure" doesn't say
  whether the role lost its login, the server is down or a query failed.
- **The batch workflow is not a required check.** It runs when scenario, pipeline, compose or migration files
  change, and on demand. A change elsewhere that breaks a slow scenario is caught only at the next batch run.
- **The batch's waits are tuned to GitHub's runners.** S15 pair A needed 59 s and then 89 s for ten outbox rows
  while the ledger was rate limited. Its limit was 120 s and is now 300 s; other waits may be as tight on a slower
  machine.
- **Stored logs are the minimal version.** Lines are cut at 500 characters and carry IDs only where the service
  passes them; today's services mostly log plain messages. A redaction filter and trace IDs on every line are M4.
- **A scenario's planted log line is written by the trigger, not by a service.** It is labelled as coming from the
  posting service because S17 tests text that looks like a real log line.
- **Stored logs can still be lost, but no longer silently.** A full queue drops lines; a write that fails 20
  times in a row drops its batch. Each failed write is reported on the service's stderr. Until PR #18 a single
  line written by itself was always lost (a one-row insert was refused for the insert-only role), so stored logs
  from before that fix are incomplete: lines that arrived alone are missing.
- **Runs are limited to 0 to 12 per scenario** (234 scenario runs), by the BR-/ML-#### stay ID shape.
- **A 10/10 local repeat run didn't catch a timing race** that a faster CI runner hit (verification log M3 #7). The
  M2 repeat runs show stability on the owner's machine, not on every machine.
- **The predictions are the builder's.** Which scenarios the rules handle alone (9 of 18) was written by Claude Code
  from the M2 code, with nobody else reviewing it.
