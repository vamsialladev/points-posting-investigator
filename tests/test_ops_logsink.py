"""The stored-log handler never hurts the service it logs for (RFC-0002 Phase 2). Offline, with a fake writer."""

from __future__ import annotations

import logging

import pytest

from app.ops import logsink
from app.ops.tables import MESSAGE_LIMIT
from app.scenarios import catalog


class Writer:
    def __init__(self, fail: bool = False) -> None:
        self.fail, self.batches = fail, []

    def __call__(self, rows: list[dict]) -> None:
        if self.fail:
            raise ConnectionError("database is down")
        self.batches.append(rows)

    @property
    def rows(self) -> list[dict]:
        return [row for batch in self.batches for row in batch]


def logger_with(handler: logging.Handler, name: str = "app.pipeline.posting") -> logging.Logger:
    logger = logging.Logger(name, level=logging.DEBUG)  # not registered: nothing leaks between tests
    logger.addHandler(handler)
    return logger


def test_a_line_is_stored_with_its_ids_and_level():
    writer = Writer()
    handler = logsink.OpsLogHandler("posting", writer)
    extra = {"correlation_id": "corr-1", "trace_id": "0af7651916cd43dd8448eb211c80319c", "event_id": "e-1"}
    logger_with(handler).warning("dead-lettered %s/%s@%s: %s", "stay.checked_out", 1, 42, "schema", extra=extra)
    assert handler.drain() == 1
    assert writer.rows == [
        {
            "service": "posting",
            "level": "WARNING",
            "logger": "app.pipeline.posting",
            "message": "dead-lettered stay.checked_out/1@42: schema",
            **extra,
        }
    ]
    assert handler.stats.stored == 1


def test_a_line_without_ids_stores_nulls_and_a_long_message_is_cut():
    writer = Writer()
    handler = logsink.OpsLogHandler("relay", writer)
    logger_with(handler).info("x" * (MESSAGE_LIMIT + 300))
    handler.drain()
    (row,) = writer.rows
    assert len(row["message"]) == MESSAGE_LIMIT
    assert (row["correlation_id"], row["trace_id"], row["event_id"]) == (None, None, None)


def test_an_exception_is_stored_as_its_type_never_its_traceback():
    writer = Writer()
    handler = logsink.OpsLogHandler("posting", writer)
    try:
        raise KeyError("secret-looking detail")
    except KeyError:
        logger_with(handler).exception("posting cycle failed")
    handler.drain()
    assert writer.rows[0]["message"] == "posting cycle failed [KeyError]"


def test_a_full_queue_drops_lines_and_counts_them_without_raising():
    writer = Writer()
    handler = logsink.OpsLogHandler("posting", writer, capacity=3)
    logger = logger_with(handler)
    for n in range(10):
        logger.info("line %s", n)
    assert handler.stats.dropped_full == 7
    assert handler.drain() == 3 and [row["message"] for row in writer.rows] == ["line 0", "line 1", "line 2"]


def test_a_failed_write_keeps_its_lines_and_stores_them_in_order_once_the_database_is_back():
    """The first version dropped a failed batch at once, silently. During scenario S07 that lost four of six retry
    lines and left no trace of why (verification log, M3 Phase 2)."""
    writer, said = Writer(fail=True), []
    handler = logsink.OpsLogHandler("posting", writer, batch=2, report=said.append)
    logger = logger_with(handler)
    for n in range(5):
        logger.error("line %s", n)  # must not raise
    for _ in range(3):
        handler.drain()  # three cycles while the database is down: nothing raised, nothing lost, nothing spun
    assert (handler.stats.stored, handler.stats.dropped_failed) == (0, 0)
    assert said and said[0] == "ops log sink (posting): 2 line(s) not stored yet, try 1 of 20: ConnectionError"
    writer.fail = False
    handler.drain()
    assert [row["message"] for row in writer.rows] == [f"line {n}" for n in range(5)], "all of them, in order"
    assert (handler.stats.stored, handler.stats.dropped_failed) == (5, 0)


def test_a_batch_that_keeps_failing_is_dropped_after_max_tries_and_later_lines_still_get_through():
    class Picky(Writer):
        def __call__(self, rows: list[dict]) -> None:
            if any(row["message"] == "poison" for row in rows):
                raise ValueError("this batch can never be stored")
            super().__call__(rows)

    writer, said = Picky(), []
    handler = logsink.OpsLogHandler("posting", writer, batch=1, max_tries=3, report=said.append)
    logger = logger_with(handler)
    logger.info("poison")
    logger.info("fine")
    for _ in range(4):
        handler.drain()
    assert handler.stats.dropped_failed == 1 and [row["message"] for row in writer.rows] == ["fine"]
    assert any("try 3 of 3: ValueError" in line for line in said) or len(said) == 1  # reports are throttled


def test_the_failure_report_names_the_error_type_and_sql_state_never_the_log_text():
    class Refused(Exception):  # shaped like a SQLAlchemy error wrapping a driver error
        def __init__(self) -> None:
            super().__init__("INSERT ... VALUES ('the secret-looking log line')")
            self.orig = type("InsufficientPrivilege", (Exception,), {"sqlstate": "42501"})()

    class Failing(Writer):
        def __call__(self, rows: list[dict]) -> None:
            raise Refused()

    said: list[str] = []
    handler = logsink.OpsLogHandler("relay", Failing(), report=said.append)
    logger_with(handler).warning("the secret-looking log line")
    handler.drain()
    assert said == [
        "ops log sink (relay): 1 line(s) not stored yet, try 1 of 20: Refused/InsufficientPrivilege, SQL state 42501"
    ]


def test_a_reporter_that_fails_does_not_break_the_handler():
    def broken(_text: str) -> None:
        raise OSError("stderr is closed")

    handler = logsink.OpsLogHandler("posting", Writer(fail=True), report=broken)
    logger_with(handler).info("line")
    handler.drain()  # must not raise
    assert handler.stats.dropped_failed == 0


def test_a_broken_format_string_does_not_raise():
    writer = Writer()
    handler = logsink.OpsLogHandler("posting", writer)
    handler.emit(logging.LogRecord("x", logging.INFO, __file__, 1, "%s and %s", ("only one",), None))
    handler.drain()
    assert writer.rows[0]["message"] == "%s and %s"


def test_lines_are_written_in_batches_and_the_drivers_own_loggers_are_ignored():
    writer = Writer()
    handler = logsink.OpsLogHandler("posting", writer, batch=4)
    logger = logger_with(handler)
    for n in range(10):
        logger.info("line %s", n)
    logger_with(handler, "sqlalchemy.engine.Engine").info("INSERT INTO log_event ...")
    logger_with(handler, "psycopg.pool").warning("reconnecting")
    assert handler.drain() == 10
    assert [len(batch) for batch in writer.batches] == [4, 4, 2]


def test_the_background_thread_writes_and_close_flushes_what_is_left():
    writer = Writer()
    handler = logsink.OpsLogHandler("posting", writer)
    handler.start(interval=0.01)
    logger_with(handler).info("one")
    handler.close()
    assert [row["message"] for row in writer.rows] == ["one"]


def test_planted_instruction_text_is_stored_as_plain_data():
    writer = Writer()
    handler = logsink.OpsLogHandler("posting", writer)
    logger_with(handler).warning(
        catalog.INJECTION_LOG_MESSAGE, extra={"correlation_id": catalog.INJECTION_CORRELATION_ID}
    )
    handler.drain()
    assert writer.rows[0]["message"] == catalog.INJECTION_LOG_MESSAGE
    assert writer.rows[0]["correlation_id"] == catalog.INJECTION_CORRELATION_ID


def test_without_a_password_nothing_is_installed():
    root = logging.Logger("root-for-test")
    assert logsink.install("posting", environ={}, root=root) is None
    assert root.handlers == []


def test_with_a_password_the_handler_is_installed_at_info_and_started():
    """No connection is made here: the engine connects only when a batch is written. The real write is tested as
    the real role in tests/test_ops_postgres.py."""
    root = logging.Logger("root-for-test")
    handler = logsink.install(
        "posting", environ={"OPS_DB_PASSWORD": "not-a-real-one", "OPS_LOG_LEVEL": "nonsense"}, root=root
    )
    assert handler is not None
    try:
        assert root.handlers == [handler] and handler.level == logging.INFO  # an unknown level falls back to INFO
        assert handler._thread is not None and handler._thread.is_alive()
        writer = Writer()
        handler.writer = writer  # the thread now writes here instead of to a database
        root.debug("below the level: not stored")
        root.info("stored")
    finally:
        handler.close()
    assert [row["message"] for row in writer.rows] == ["stored"]


def test_the_insert_only_tables_never_ask_for_the_new_row_back():
    """`RETURNING` needs SELECT, which the services' role doesn't have. Offline this can only check the setting;
    tests/test_ops_postgres.py stores single lines as the real role."""
    from sqlalchemy import insert
    from sqlalchemy.dialects import postgresql

    from app.ops import tables

    for table in (tables.log_event, tables.alert_evaluation):
        assert table.implicit_returning is False, table.name
        compiled = str(insert(table).compile(dialect=postgresql.dialect()))
        assert "RETURNING" not in compiled, table.name


def test_sizes_must_be_positive():
    for bad in ({"capacity": 0}, {"batch": 0}):
        with pytest.raises(ValueError):
            logsink.OpsLogHandler("posting", Writer(), **bad)
