"""The posting service's tables: the posting record and the transactional outbox (RFC-0001 D5, D6, D10).

- `posting.event_id` is the primary key: one posting per event, so a redelivered event can't add a second outbox row.
- `UNIQUE(stay_id, revision)` stops a re-emitted stay under a new event ID (a producer bug) from posting twice.
- The outbox payload is the logical record as JSON. The relay serializes it with the schema registry at publish
  time, so a registry outage delays publishing but never blocks a posting.
"""

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Identity,
    Index,
    Integer,
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

outbox = Table(
    "outbox",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("topic", Text, nullable=False),
    Column("message_key", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("headers", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("published_at", DateTime(timezone=True)),
    Column("attempts", Integer, nullable=False, server_default=text("0")),
    Column("last_error", Text),
    Index("outbox_unpublished_idx", "id", postgresql_where=text("published_at IS NULL")),
)
