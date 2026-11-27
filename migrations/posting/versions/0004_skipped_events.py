"""Skipped events: stale stay revisions, recorded and not credited (RFC-0001 D10).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skipped_event",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("stay_id", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("member_number", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("latest_revision", sa.Integer()),
        sa.Column("correlation_id", sa.Text(), nullable=False),
        sa.Column("skipped_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("reason IN ('stale_revision')", name="skipped_reason_known"),
    )


def downgrade() -> None:
    op.drop_table("skipped_event")
