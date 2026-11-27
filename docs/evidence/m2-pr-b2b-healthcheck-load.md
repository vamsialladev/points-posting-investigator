# The stack's own idle load, before and after slowing the health checks (2026-11-27)

Local machine, 8 logical cores. The same stack (9 services, idle: no test running) both times. Measured with
`Get-Counter '\Process(vmmemwsl)\% Processor Time'` (the Docker Desktop VM), divided by the core count, so the
numbers are a share of the whole machine.

| | Health-check timing | Samples | Docker VM, mean | Docker VM, max |
|---|---|---|---|---|
| Before | every 3 s (Postgres, ledger, posting, retry worker, relay) or 5 s (Kafka, Karapace), always | 12 × 5 s | **22.8 %** | 28.6 % |
| After | every 2 s during a 120 s start period, then every 30 s (`start_interval`) | 24 × 5 s | **9.2 %** | 22.3 % |

Why it mattered:
- **What each probe costs:** Kafka's probe (`kafka-broker-api-versions.sh`) starts a whole JVM, and the others start
  a Python interpreter. `docker stats` caught them at Kafka 161–226 %, the retry worker 66 % and posting 53 %, on a
  stack doing nothing.
- **Against the quiet check:** that load alone was close to `scripts\quiet_check.ps1`'s 25 % mean limit, and every
  test run shared the machine with it.

After the change:
- `scripts\stack.ps1 up` (with an image build) took 65 s to all-healthy.
- `run_integration.py -k "test_kafka_stack or one_row_becomes_one_message"`: 5 passed.

Other load at the time, from other projects:
- the first quiet check, BUSY: `m2-pr-b2b-quiet-check-1.md`
- Python jobs from other repos, Defender (`msmpeng`) and the desktop
