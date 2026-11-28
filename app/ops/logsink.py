"""Store a service's log lines in the `ops` database, so an investigator can cite a row (RFC-0002 Phase 2).

    install("posting")     # in a service's main(), after logging.basicConfig

Rules, each tested:
- **Logging never hurts the service.** `emit` only puts a small record on a bounded queue. A background thread writes
  batches. Nothing is raised into the service. A full queue drops lines and counts them. A failed write keeps its
  batch and tries again on the next cycles, and says so on stderr (the error's type and SQL state, never the text
  of a log line); after 20 tries the batch is dropped and counted.
- **Bounded:** the message is cut at 500 characters, and only INFO and above is stored by default.
- **Insert-only:** the handler connects as `ops_app`, which can't read, change or delete a log line.
- **IDs when the line has them:** `correlation_id`, `trace_id` and `event_id` from the record's `extra`.
- **Off without a password:** with no `OPS_DB_PASSWORD` nothing is installed, and the service logs to stderr as before.

This is the minimal version of OBS-02. A redaction filter for payloads is Milestone 4; today's services log IDs,
offsets and error classes, never event bodies.
"""

from __future__ import annotations

import contextlib
import logging
import os
import queue
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.ops.tables import MESSAGE_LIMIT

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
ID_FIELDS = ("correlation_id", "trace_id", "event_id")
Writer = Callable[[list[dict[str, Any]]], None]


@dataclass
class SinkStats:
    stored: int = 0
    dropped_full: int = 0  # the queue was full
    dropped_failed: int = 0  # the database refused or was down


def _stderr(text: str) -> None:
    print(text, file=sys.stderr, flush=True)  # not through logging: this reports the log handler's own trouble


def row_of(service: str, record: logging.LogRecord) -> dict[str, Any]:
    try:
        message = record.getMessage()
    except Exception:  # a broken format string must not break the service
        message = str(record.msg)
    if record.exc_info and record.exc_info[0] is not None:
        message = f"{message} [{record.exc_info[0].__name__}]"  # the exception's type, never its traceback
    level = record.levelname if record.levelname in LEVELS else "INFO"
    row: dict[str, Any] = {
        "service": service,
        "level": level,
        "logger": record.name[:200],
        "message": message[:MESSAGE_LIMIT],
    }
    for name in ID_FIELDS:
        value = getattr(record, name, None)
        row[name] = str(value)[:200] if value else None
    return row


class OpsLogHandler(logging.Handler):
    def __init__(
        self,
        service: str,
        writer: Writer,
        *,
        capacity: int = 1000,
        batch: int = 50,
        max_tries: int = 20,
        report: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        if capacity < 1 or batch < 1 or max_tries < 1:
            raise ValueError("capacity, batch and max_tries must be at least 1")
        self.service, self.writer, self.batch = service, writer, batch
        self.stats = SinkStats()
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=capacity)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._held: list[dict[str, Any]] = []  # a batch whose write failed, kept for the next cycles
        self._held_tries = 0
        self._last_report = 0.0
        self.max_tries = max_tries
        self.report = report

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(("sqlalchemy", "psycopg")):
            return  # the sink's own database driver must not feed the sink
        try:
            self._queue.put_nowait(row_of(self.service, record))
        except queue.Full:
            self.stats.dropped_full += 1
        except Exception:  # never raise into the service
            self.stats.dropped_failed += 1

    def drain(self) -> int:
        """Write what is queued, in batches. Returns how many rows were taken off the queue.

        A batch whose write fails is **kept and tried again** on the next cycles (up to `max_tries`), and the failure
        is reported on stderr with its type and SQL state, never the log text. The first version dropped such a batch
        at once and only counted it in memory: during scenario S07 that lost four of six retry lines with no trace
        of why (verification log, M3 Phase 2). While a batch is held, nothing newer is written, so order is kept;
        the queue is bounded, so a long outage still costs lines rather than memory."""
        taken = 0
        while True:
            if self._held:
                rows = self._held
            else:
                rows = []
                while len(rows) < self.batch:
                    try:
                        rows.append(self._queue.get_nowait())
                    except queue.Empty:
                        break
                if not rows:
                    return taken
                taken += len(rows)
            try:
                self.writer(rows)
            except Exception as exc:  # a database failure must not reach the service
                self._held_tries += 1
                self._say(exc, len(rows))
                if self._held_tries >= self.max_tries:
                    self.stats.dropped_failed += len(rows)
                    self._held, self._held_tries = [], 0
                    continue
                self._held = rows
                return taken  # try again next cycle; don't spin
            self.stats.stored += len(rows)
            self._held, self._held_tries = [], 0

    def _say(self, exc: Exception, rows: int) -> None:
        """One line on stderr per failure streak step, at most every 5 s. Type and SQL state only."""
        now = time.monotonic()
        if now - self._last_report < 5.0 and self._held_tries > 1:
            return
        self._last_report = now
        cause = getattr(exc, "orig", None)
        state = getattr(cause, "sqlstate", None)
        detail = type(exc).__name__ + (f"/{type(cause).__name__}" if cause is not None else "")
        text = (
            f"ops log sink ({self.service}): {rows} line(s) not stored yet, try {self._held_tries} of {self.max_tries}:"
            f" {detail}" + (f", SQL state {state}" if state else "")
        )
        with contextlib.suppress(Exception):  # reporting a logging failure must never fail the service
            (self.report or _stderr)(text)

    def start(self, interval: float = 0.5) -> None:
        def loop() -> None:
            while not self._stop.wait(interval):
                self.drain()
            self.drain()

        self._thread = threading.Thread(target=loop, name="ops-log-sink", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        else:
            self.drain()
        super().close()


def postgres_writer(engine: Any) -> Writer:
    from sqlalchemy import insert

    from app.ops.tables import log_event

    def write(rows: list[dict[str, Any]]) -> None:
        with engine.begin() as conn:
            conn.execute(insert(log_event), rows)

    return write


def install(
    service: str, environ: Mapping[str, str] | None = None, root: logging.Logger | None = None
) -> OpsLogHandler | None:
    """Add the handler to the root logger. Returns None, and changes nothing, when OPS_DB_PASSWORD isn't set."""
    env = os.environ if environ is None else environ
    password = env.get("OPS_DB_PASSWORD", "")
    if not password:
        return None
    from sqlalchemy import create_engine

    from app.db.roles import Database, runtime_url

    engine = create_engine(
        runtime_url(
            Database("ops", env.get("DB_PREFIX", "")),
            password,
            host=env.get("POSTGRES_HOST", "localhost"),
            port=int(env.get("POSTGRES_PORT", "5432")),
        ),
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
    )
    handler = OpsLogHandler(service, postgres_writer(engine))
    level = env.get("OPS_LOG_LEVEL", "INFO")
    handler.setLevel(level if level in LEVELS else "INFO")
    (root or logging.getLogger()).addHandler(handler)
    handler.start()
    return handler
