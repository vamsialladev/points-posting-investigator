"""The posting service's tables: postings, the transactional outbox and parked events (RFC-0001 D5, D6, D10; ADR-0016).

- `posting.event_id` is the primary key: one posting per event, so a redelivered event can't add a second outbox row.
- `UNIQUE(stay_id, revision)` stops a re-emitted stay under a new event ID (a producer bug) from posting twice.
- The outbox payload is the logical record as JSON. The relay serializes it with the schema registry at publish
  time, so a registry outage delays publishing but never blocks a posting.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Identity,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

posting = Table(
    "posting",
    metadata,
    Column("event_id", Text, primary_key=True),
    Column("stay_id", Text, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("member_number", Text, nullable=False),
    Column("stay_points", Integer, nullable=False),  # points this revision of the stay earns
    Column("credited_points", Integer, nullable=False),  # what was credited: the difference for a correction
    Column("ledger_entry_id", Text, nullable=False),
    Column("correlation_id", Text, nullable=False),
    Column("posted_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("stay_id", "revision", name="posting_stay_revision_key"),
)

# Delivery state (migration 0002, ADR-0014):
#   pending   -> waiting; due when next_attempt_at <= now()
#   in_flight -> claimed by `claimed_by` until `lease_until`; a crashed relay's rows become claimable when it expires
#   published -> delivered to Kafka (published_at set)
#   dead      -> gave up after max attempts (dead_at set): the dead-letter table. Never replayed automatically (M7).
# The relay may only ever claim the OLDEST open row of a member (message_key), which keeps per-member order across
# several relays: tests/test_relay_kafka.py.
OPEN_STATUSES = ("pending", "in_flight")

outbox = Table(
    "outbox",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("topic", Text, nullable=False),
    Column("message_key", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("headers", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("trace_context", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("status", Text, nullable=False, server_default=text("'pending'")),
    Column("next_attempt_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("claimed_by", Text),
    Column("lease_until", DateTime(timezone=True)),
    Column("published_at", DateTime(timezone=True)),
    Column("dead_at", DateTime(timezone=True)),
    Column("attempts", Integer, nullable=False, server_default=text("0")),
    Column("last_error", Text),
    CheckConstraint("status IN ('pending', 'in_flight', 'published', 'dead')", name="outbox_status_known"),
    CheckConstraint("(status = 'published') = (published_at IS NOT NULL)", name="outbox_published_consistent"),
    CheckConstraint("(status = 'dead') = (dead_at IS NOT NULL)", name="outbox_dead_consistent"),
    CheckConstraint("(status = 'in_flight') = (lease_until IS NOT NULL)", name="outbox_lease_consistent"),
    Index("outbox_open_by_key_idx", "message_key", "id", postgresql_where=text("status IN ('pending', 'in_flight')")),
    Index("outbox_due_idx", "next_attempt_at", postgresql_where=text("status = 'pending'")),
)

# Parked events (migration 0003, ADR-0016): events waiting for a retry, in arrival order per member.
#   pending   -> waiting; due when next_attempt_at <= now(), and only the member's OLDEST open one is claimable
#   in_flight -> claimed by a retry worker until lease_until
#   done      -> posted (the posting and outbox rows were written in the same transaction as this change)
#   dead      -> gave up after max_attempts permanent failures; the original bytes went to the DLQ topic first
# `attempts` counts permanent failures only (they dead-letter at the maximum); `transient_failures` counts outages,
# which never dead-letter. The original message (raw_key, raw_value, raw_headers) is kept so the DLQ copy is exact.
PARKED_OPEN = ("pending", "in_flight")

parked_event = Table(
    "parked_event",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("event_id", Text, nullable=False),
    Column("member_number", Text, nullable=False),
    Column("stay_id", Text, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("raw_key", LargeBinary),
    Column("raw_value", LargeBinary, nullable=False),
    Column("raw_headers", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("source_topic", Text, nullable=False),
    Column("source_partition", Integer, nullable=False),
    Column("source_offset", BigInteger, nullable=False),
    Column("status", Text, nullable=False, server_default=text("'pending'")),
    Column("attempts", Integer, nullable=False, server_default=text("0")),
    Column("transient_failures", Integer, nullable=False, server_default=text("0")),
    Column("next_attempt_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("claimed_by", Text),
    Column("lease_until", DateTime(timezone=True)),
    Column("error_class", Text),
    Column("last_error", Text),
    Column("first_failed_at", DateTime(timezone=True)),
    Column("last_failed_at", DateTime(timezone=True)),
    Column("parked_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("done_at", DateTime(timezone=True)),
    Column("dead_at", DateTime(timezone=True)),
    UniqueConstraint("event_id", name="parked_event_event_id_key"),
    CheckConstraint("status IN ('pending', 'in_flight', 'done', 'dead')", name="parked_status_known"),
    CheckConstraint("(status = 'done') = (done_at IS NOT NULL)", name="parked_done_consistent"),
    CheckConstraint("(status = 'dead') = (dead_at IS NOT NULL)", name="parked_dead_consistent"),
    CheckConstraint("(status = 'in_flight') = (lease_until IS NOT NULL)", name="parked_lease_consistent"),
    CheckConstraint("attempts >= 0 AND transient_failures >= 0", name="parked_counts_not_negative"),
    Index(
        "parked_open_by_member_idx", "member_number", "id", postgresql_where=text("status IN ('pending', 'in_flight')")
    ),
    Index("parked_due_idx", "next_attempt_at", postgresql_where=text("status = 'pending'")),
)
