"""The ops database: stored logs, the change feed, member questions, alert evaluations, runbook text (RFC-0002).

Revision ID: 0001
Revises:
Create Date: 2026-11-27
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
        "log_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("logged_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("service", sa.Text(), nullable=False),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("logger", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("correlation_id", sa.Text()),
        sa.Column("trace_id", sa.Text()),
        sa.Column("event_id", sa.Text()),
        sa.CheckConstraint("level IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')", name="log_level_known"),
        sa.CheckConstraint("char_length(message) <= 500", name="log_message_bounded"),
    )
    op.create_index("log_event_logged_at_idx", "log_event", ["logged_at"])
    op.create_index(
        "log_event_correlation_idx",
        "log_event",
        ["correlation_id"],
        postgresql_where=sa.text("correlation_id IS NOT NULL"),
    )
    op.create_table(
        "change_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("service", sa.Text(), nullable=False),
        sa.Column("setting", sa.Text(), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=False),
        sa.Column("new_value", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.CheckConstraint("source IN ('scenario', 'operator')", name="change_source_known"),
    )
    op.create_index("change_event_changed_at_idx", "change_event", ["changed_at"])
    op.create_table(
        "member_question",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("member_number", sa.Text(), nullable=False),
        sa.Column("stay_id", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.CheckConstraint("member_number ~ '^GR-[0-9]{5}$'", name="question_member_shape"),
        sa.CheckConstraint("stay_id ~ '^(BR|ML)-[0-9]{4}$'", name="question_stay_shape"),
    )
    op.create_table(
        "alert_evaluation",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("signals", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("missing", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.CheckConstraint("state IN ('firing', 'quiet', 'not_evaluated')", name="alert_state_known"),
    )
    op.create_index("alert_evaluation_at_idx", "alert_evaluation", ["evaluated_at"])
    op.create_table(
        "runbook_section",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("runbook", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("tag", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("runbook_section_tag_idx", "runbook_section", ["tag"], postgresql_where=sa.text("tag IS NOT NULL"))


def downgrade() -> None:
    for table in ("runbook_section", "alert_evaluation", "member_question", "change_event", "log_event"):
        op.drop_table(table)
