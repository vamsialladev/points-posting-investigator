"""The `ops` database on real Postgres: the services' role can only add log lines and alert evaluations (ADR-0019).

Each right is checked as the real role, both what is allowed and what is refused, in the `test_ops` database.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from psycopg import errors
from sqlalchemy import Engine, create_engine

from app.db.roles import Database
from app.ops import logsink
from app.scenarios import catalog
from tests.infra import PREFIX, admin_connect, role_url, runtime_connect

pytestmark = pytest.mark.postgres
OPS = Database("ops", PREFIX)
TABLES = ("log_event", "change_event", "member_question", "alert_evaluation", "runbook_section")


@pytest.fixture
def ops_engine(admin, passwords, host) -> Iterator[Engine]:
    with admin_connect(admin, OPS) as conn:
        conn.execute(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY")
    engine = create_engine(role_url(OPS, passwords, host))
    yield engine
    engine.dispose()


def test_the_handler_stores_lines_as_the_insert_only_role(ops_engine, admin):
    handler = logsink.OpsLogHandler("posting", logsink.postgres_writer(ops_engine))
    logger = logging.Logger("app.pipeline.posting")
    logger.addHandler(handler)
    logger.warning("dead-lettered %s", "stay.checked_out/0@7", extra={"correlation_id": "corr-9", "event_id": "e-9"})
    logger.info(catalog.INJECTION_LOG_MESSAGE, extra={"correlation_id": catalog.INJECTION_CORRELATION_ID})
    assert handler.drain() == 2 and (handler.stats.stored, handler.stats.dropped_failed) == (2, 0)
    with admin_connect(admin, OPS) as conn:
        rows = conn.execute(
            "SELECT service, level, message, correlation_id, event_id, logged_at IS NOT NULL FROM log_event ORDER BY id"
        ).fetchall()
    assert rows == [
        ("posting", "WARNING", "dead-lettered stay.checked_out/0@7", "corr-9", "e-9", True),
        ("posting", "INFO", catalog.INJECTION_LOG_MESSAGE, catalog.INJECTION_CORRELATION_ID, None, True),
    ]


def test_the_services_role_can_add_an_alert_evaluation(passwords, host, admin, ops_engine):
    with runtime_connect(OPS, passwords, host) as conn:
        conn.execute(
            "INSERT INTO alert_evaluation (rule, state, signals) VALUES ('postings_dropped', 'firing', '{\"a\": 1}')"
        )
    with admin_connect(admin, OPS) as conn:
        assert conn.execute("SELECT rule, state FROM alert_evaluation").fetchall() == [("postings_dropped", "firing")]


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT * FROM log_event",
        "UPDATE log_event SET message = 'rewritten'",
        "DELETE FROM log_event",
        "TRUNCATE log_event",
        "SELECT * FROM alert_evaluation",
        "DELETE FROM alert_evaluation",
        "INSERT INTO change_event (service, setting, old_value, new_value, source)"
        " VALUES ('s', 'k', 'a', 'b', 'operator')",
        "SELECT * FROM change_event",
        "INSERT INTO member_question (member_number, stay_id, question) VALUES ('GR-00001', 'BR-0001', 'q')",
        "INSERT INTO runbook_section (runbook, title, body) VALUES ('r', 't', 'b')",
        "DELETE FROM runbook_section",
        "DROP TABLE log_event",
    ],
)
def test_the_services_role_can_do_nothing_else(passwords, host, ops_engine, statement):
    with runtime_connect(OPS, passwords, host) as conn, pytest.raises(errors.InsufficientPrivilege):
        conn.execute(statement)


def test_the_database_refuses_bad_shapes_even_from_the_superuser(admin, ops_engine):
    bad = [
        "INSERT INTO log_event (service, level, logger, message) VALUES ('s', 'LOUD', 'l', 'm')",
        "INSERT INTO log_event (service, level, logger, message) VALUES ('s', 'INFO', 'l', repeat('x', 501))",
        "INSERT INTO change_event (service, setting, old_value, new_value, source)"
        " VALUES ('s', 'k', 'a', 'b', 'model')",
        "INSERT INTO member_question (member_number, stay_id, question) VALUES ('GR-1', 'BR-0001', 'q')",
        "INSERT INTO alert_evaluation (rule, state) VALUES ('r', 'maybe')",
    ]
    with admin_connect(admin, OPS) as conn:
        for statement in bad:
            with pytest.raises(errors.CheckViolation):
                conn.execute(statement)


def test_the_ops_role_cannot_reach_the_pipelines_databases(passwords, host, admin):
    url = role_url(OPS, passwords, host)
    for other in ("posting", "ledger"):
        engine = create_engine(url.set(database=Database(other, PREFIX).name))
        with pytest.raises(Exception, match=r"permission denied for database|CONNECT"):
            engine.connect()
        engine.dispose()
