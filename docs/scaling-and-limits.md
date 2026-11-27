# Scaling and limits (Milestone 2)

Simulated system on one laptop. Nothing here is load-tested yet; these are the designed limits and what would break
first. Measured numbers will come from the load generator runs and go in `docs/verification-log.md`.

| Part | Limit by design | What breaks first | The next step |
|---|---|---|---|
| Kafka | 1 broker, replication 1, 3 partitions | a broker restart stops the pipeline; 3 partitions cap the posting consumers at 3 | 3 brokers, replication 3, more partitions |
| Partition key `member_number` | one member, one partition | a very active member makes one partition hot | accept at this scale; a member-hash with more partitions |
| Posting service | one consumer, synchronous commits | throughput: one ledger call and one transaction per event | more consumers (up to the partition count) |
| Parking | head-of-line per member | a member with a long outage queues all their later events | that's intended (order); alert on the oldest parked age |
| Retry worker | several workers, `SKIP LOCKED` + lease | Postgres row locks under many workers | batch size, more workers |
| Load generator | 200 events a second, 10,000 a run (hard caps) | refuses larger runs | raise the caps only with a measured reason |
| Stay IDs | 9,999 per property (`BR-####`, `ML-####`, Stage 9's shape) | the load generator refuses runs that don't fit | longer IDs would break Stage 9's shapes |
| Ledger mock | token bucket, 50/s by default | 429s, which park events as transient | configurable through `/control/settings` |

Docker Desktop memory for the core stack: about 1.5 GB (RFC-0001).
