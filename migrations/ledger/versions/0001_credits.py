"""Ledger credits: one row per idempotency key, IDs in Stage 9's L-0000001 shape.

Revision ID: 0001
Revises:
Create Date: 2026-11-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.schema.CreateSequence(sa.Sequence("credit_entry_seq")))
    op.create_table(
        "credits",
        sa.Column(
            "entry_id",
            sa.Text(),
            primary_key=True,
            server_default=sa.text("('L-'::text || lpad((nextval('credit_entry_seq'::regclass))::text, 7, '0'::text))"),
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("member_number", sa.Text(), nullable=False),
        sa.Column("stay_id", sa.Text(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("idempotency_key", name="credits_idempotency_key_key"),
        sa.CheckConstraint("member_number ~ '^GR-[0-9]{5}$'", name="credits_member_number_format"),
        sa.CheckConstraint("stay_id ~ '^(BR|ML)-[0-9]{4}$'", name="credits_stay_id_format"),
    )


def downgrade() -> None:
    op.drop_table("credits")
    op.execute(sa.schema.DropSequence(sa.Sequence("credit_entry_seq")))
