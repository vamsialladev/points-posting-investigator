"""The `ops` database: stored evidence the investigator can cite by row (RFC-0002 Phase 2, ADR-0019).

- `log_event`: structured log lines from the services, with correlation and trace IDs where the line has them.
- `change_event`: the "what changed" feed (simulated config changes).
- `member_question`: a member asking about a stay (scenario S16).
- `alert_evaluation`: every evaluation of an alert rule, with the signal values it read.
- `runbook_section`: runbook text; full-text search comes with the investigator's `search_runbooks`.

Everything here is text written by services, scenarios or people. To an investigator it is data, never instructions.
The services' role (`ops_app`) may only INSERT log lines and alert evaluations: it can't read, change or delete.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Identity,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

MESSAGE_LIMIT = 500  # a log line is cut here before it is stored

log_event = Table(
    "log_event",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("logged_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("service", Text, nullable=False),
    Column("level", Text, nullable=False),
    Column("logger", Text, nullable=False),
    Column("message", Text, nullable=False),
    Column("correlation_id", Text),
    Column("trace_id", Text),
    Column("event_id", Text),
    CheckConstraint("level IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')", name="log_level_known"),
    CheckConstraint(f"char_length(message) <= {MESSAGE_LIMIT}", name="log_message_bounded"),
    Index("log_event_logged_at_idx", "logged_at"),
    Index("log_event_correlation_idx", "correlation_id", postgresql_where=text("correlation_id IS NOT NULL")),
    # No `RETURNING id` on insert: RETURNING needs SELECT, and the services' role has INSERT only. With the
    # default, a one-row insert asked for the new id and was refused (SQL state 42501), while a many-row insert
    # didn't ask and worked: single log lines were lost (found in scenario S07; verification log, M3 Phase 2).
    implicit_returning=False,
)

change_event = Table(
    "change_event",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("changed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("service", Text, nullable=False),
    Column("setting", Text, nullable=False),
    Column("old_value", Text, nullable=False),
    Column("new_value", Text, nullable=False),
    Column("source", Text, nullable=False),
    CheckConstraint("source IN ('scenario', 'operator')", name="change_source_known"),
    Index("change_event_changed_at_idx", "changed_at"),
)

member_question = Table(
    "member_question",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("asked_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("member_number", Text, nullable=False),
    Column("stay_id", Text, nullable=False),
    Column("question", Text, nullable=False),
    CheckConstraint("member_number ~ '^GR-[0-9]{5}$'", name="question_member_shape"),
    CheckConstraint("stay_id ~ '^(BR|ML)-[0-9]{4}$'", name="question_stay_shape"),
)

alert_evaluation = Table(
    "alert_evaluation",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("evaluated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("rule", Text, nullable=False),
    Column("state", Text, nullable=False),
    Column("signals", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("missing", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    CheckConstraint("state IN ('firing', 'quiet', 'not_evaluated')", name="alert_state_known"),
    Index("alert_evaluation_at_idx", "evaluated_at"),
    implicit_returning=False,  # the services' role may INSERT here but not SELECT (see log_event)
)

runbook_section = Table(
    "runbook_section",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("runbook", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("body", Text, nullable=False),
    Column("version", Integer, nullable=False, server_default=text("1")),
    Column("tag", Text),  # set on text a scenario planted, so its reset can remove exactly that
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("runbook_section_tag_idx", "tag", postgresql_where=text("tag IS NOT NULL")),
)
