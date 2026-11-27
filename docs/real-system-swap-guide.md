# Swapping the simulation for real systems

Everything in Stage 10 is simulated. This is what a real deployment would replace, and what has to stay true.

| Simulated here | A real system | What must stay true |
|---|---|---|
| Producer / load generator (`app/pipeline/producer.py`, `loadgen.py`) | the property-management system's checkout feed | Avro `stay.checked_out` with `event_id`, `revision`, a member key; a resend keeps the `event_id` |
| Ledger mock (`app/ledger/`) | the loyalty ledger's posting API | idempotent credits keyed by `stay_id:revision`; a 409 for the same key with other points; a status lookup |
| Kafka + Karapace in Docker | a managed Kafka (MSK, Confluent Cloud) and its registry | `BACKWARD_TRANSITIVE` subjects; the DLQ and `points.posted` topics; replication above 1 |
| Postgres in Docker | a managed Postgres | the same roles: runtime roles can't delete or rewrite postings, credits or parked events |
| Synthetic members and stays (`seed.py`) | real member data | **out of scope for this portfolio:** real data needs the privacy work in M12 first |

Not swappable without changing the design: the ledger's idempotency key and the per-member partition key.
