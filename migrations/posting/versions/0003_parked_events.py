"""Parked events: retries in arrival order per member, replacing retry topics (ADR-0016).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "parked_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("member_number", sa.Text(), nullable=False),
        sa.Column("stay_id", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("raw_key", sa.LargeBinary()),
        sa.Column("raw_value", sa.LargeBinary(), nullable=False),
        sa.Column("raw_headers", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source_topic", sa.Text(), nullable=False),
        sa.Column("source_partition", sa.Integer(), nullable=False),
        sa.Column("source_offset", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("transient_failures", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("claimed_by", sa.Text()),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("error_class", sa.Text()),
        sa.Column("last_error", sa.Text()),
        sa.Column("first_failed_at", sa.DateTime(timezone=True)),
        sa.Column("last_failed_at", sa.DateTime(timezone=True)),
        sa.Column("parked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("done_at", sa.DateTime(timezone=True)),
        sa.Column("dead_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("event_id", name="parked_event_event_id_key"),
        sa.CheckConstraint("status IN ('pending', 'in_flight', 'done', 'dead')", name="parked_status_known"),
        sa.CheckConstraint("(status = 'done') = (done_at IS NOT NULL)", name="parked_done_consistent"),
        sa.CheckConstraint("(status = 'dead') = (dead_at IS NOT NULL)", name="parked_dead_consistent"),
        sa.CheckConstraint("(status = 'in_flight') = (lease_until IS NOT NULL)", name="parked_lease_consistent"),
        sa.CheckConstraint("attempts >= 0 AND transient_failures >= 0", name="parked_counts_not_negative"),
    )
    op.create_index(
        "parked_open_by_member_idx",
        "parked_event",
        ["member_number", "id"],
        postgresql_where=sa.text("status IN ('pending', 'in_flight')"),
    )
    op.create_index(
        "parked_due_idx", "parked_event", ["next_attempt_at"], postgresql_where=sa.text("status = 'pending'")
    )


def downgrade() -> None:
    op.drop_index("parked_due_idx", table_name="parked_event")
    op.drop_index("parked_open_by_member_idx", table_name="parked_event")
    op.drop_table("parked_event")
