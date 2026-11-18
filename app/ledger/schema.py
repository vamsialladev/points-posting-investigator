"""The ledger mock's table: its own database, the simulated system of record (RFC-0001 D9, D11).

`UNIQUE(idempotency_key)` is the last guard against a double credit: Postgres refuses a second row for one key, whatever
the application code does. The runtime role can only SELECT and INSERT (app/db/roles.py), so a credit can't be edited
or removed either. Migrations in migrations/ledger/ create exactly this; `python -m app.db.migrate check` proves they
match.
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    MetaData,
    Sequence,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)

metadata = MetaData()

credit_entry_seq = Sequence("credit_entry_seq", metadata=metadata)

credits = Table(
    "credits",
    metadata,
    # Stage 9's ledger-entry shape: L-0000001.
    Column(
        "entry_id",
        Text,
        primary_key=True,
        server_default=text("('L-'::text || lpad((nextval('credit_entry_seq'::regclass))::text, 7, '0'::text))"),
    ),
    Column("idempotency_key", Text, nullable=False),
    Column("request_hash", Text, nullable=False),
    Column("member_number", Text, nullable=False),
    Column("stay_id", Text, nullable=False),
    Column("points", Integer, nullable=False),
    Column("correlation_id", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("idempotency_key", name="credits_idempotency_key_key"),
    CheckConstraint("member_number ~ '^GR-[0-9]{5}$'", name="credits_member_number_format"),
    CheckConstraint("stay_id ~ '^(BR|ML)-[0-9]{4}$'", name="credits_stay_id_format"),
)
