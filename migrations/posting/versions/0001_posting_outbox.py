"""Posting records and the transactional outbox.

Revision ID: 0001
Revises:
Create Date: 2026-11-17
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "posting",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("stay_id", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("member_number", sa.Text(), nullable=False),
        sa.Column("stay_points", sa.Integer(), nullable=False),
        sa.Column("credited_points", sa.Integer(), nullable=False),
        sa.Column("ledger_entry_id", sa.Text(), nullable=False),
        sa.Column("correlation_id", sa.Text(), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("stay_id", "revision", name="posting_stay_revision_key"),
    )
    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("message_key", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("headers", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text()),
    )
    op.create_index("outbox_unpublished_idx", "outbox", ["id"], postgresql_where=sa.text("published_at IS NULL"))


def downgrade() -> None:
    op.drop_index("outbox_unpublished_idx", table_name="outbox")
    op.drop_table("outbox")
    op.drop_table("posting")
