# Tech-debt register

Known shortcuts, each with why it was taken and when it gets paid. New items go here as they're found.

| # | Debt | Why it's there | Pay it when |
|---|---|---|---|
| 1 | ~~No dedicated rebalance test (a second consumer joining mid-stream)~~ Paid in M2 PR-C (`test_a_second_consumer_joining_mid_stream_loses_nothing_and_credits_nothing_twice`) | M2 time went to the producer silent-loss bug (ADR-0017) | done |
| 2 | The ledger `members` table isn't built (RFC-0001 change 6) | nothing reads it yet (ADR-0018); none of the 18 scenarios needs it (ADR-0019) | v2, or sooner if a new scenario needs unknown-member failures |
| 3 | Kafka has no volume: `stack.ps1 down` loses topics and messages | a throwaway local stack; tests create their own topics | if a demo needs messages kept across restarts |
| 4 | The local schema check is structural, flat records only | our schemas are flat; the registry is the authority | the first nested schema |
| 5 | A correction that arrives before its original holds up that member until it is dead-lettered | strict per-member order (ADR-0016, ADR-0018) | if the catalog shows this often (M3, M9) |
| 6 | Karapace's health check only reads, so a stuck write path looks healthy | the stock image's check | M4: a write probe in the alerts |
| 7 | Scratch topics from tests are deleted best-effort; a failed delete is silent | the test teardown ignores errors | if leftovers slow the stack again |
