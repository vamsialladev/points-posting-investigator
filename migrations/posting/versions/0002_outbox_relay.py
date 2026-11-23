"""Outbox delivery state for several relays: status, leases, backoff, dead-letter, trace context (ADR-0014).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-22
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("outbox", sa.Column("trace_context", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("outbox", sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")))
    op.add_column(
        "outbox", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )
    op.add_column("outbox", sa.Column("claimed_by", sa.Text()))
    op.add_column("outbox", sa.Column("lease_until", sa.DateTime(timezone=True)))
    op.add_column("outbox", sa.Column("dead_at", sa.DateTime(timezone=True)))
    # Rows from before 0002 that were already published keep that state.
    op.execute("UPDATE outbox SET status = 'published' WHERE published_at IS NOT NULL")
    op.create_check_constraint(
        "outbox_status_known", "outbox", "status IN ('pending', 'in_flight', 'published', 'dead')"
    )
    op.create_check_constraint(
        "outbox_published_consistent", "outbox", "(status = 'published') = (published_at IS NOT NULL)"
    )
    op.create_check_constraint("outbox_dead_consistent", "outbox", "(status = 'dead') = (dead_at IS NOT NULL)")
    op.create_check_constraint(
        "outbox_lease_consistent", "outbox", "(status = 'in_flight') = (lease_until IS NOT NULL)"
    )
    op.drop_index("outbox_unpublished_idx", table_name="outbox")
    op.create_index(
        "outbox_open_by_key_idx",
        "outbox",
        ["message_key", "id"],
        postgresql_where=sa.text("status IN ('pending', 'in_flight')"),
    )
    op.create_index("outbox_due_idx", "outbox", ["next_attempt_at"], postgresql_where=sa.text("status = 'pending'"))


def downgrade() -> None:
    op.drop_index("outbox_due_idx", table_name="outbox")
    op.drop_index("outbox_open_by_key_idx", table_name="outbox")
    op.create_index("outbox_unpublished_idx", "outbox", ["id"], postgresql_where=sa.text("published_at IS NULL"))
    for name in (
        "outbox_lease_consistent",
        "outbox_dead_consistent",
        "outbox_published_consistent",
        "outbox_status_known",
    ):
        op.drop_constraint(name, "outbox", type_="check")
    for column in ("dead_at", "lease_until", "claimed_by", "next_attempt_at", "status", "trace_context"):
        op.drop_column("outbox", column)
