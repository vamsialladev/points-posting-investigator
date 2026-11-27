"""Store a service's log lines in the `ops` database, so an investigator can cite a row (RFC-0002 Phase 2).

    install("posting")     # in a service's main(), after logging.basicConfig

Rules, each tested:
- **Logging never hurts the service.** `emit` only puts a small record on a bounded queue. A background thread writes
  batches. A full queue or a database failure drops lines and counts them; nothing is raised into the service.
- **Bounded:** the message is cut at 500 characters, and only INFO and above is stored by default.
- **Insert-only:** the handler connects as `ops_app`, which can't read, change or delete a log line.
- **IDs when the line has them:** `correlation_id`, `trace_id` and `event_id` from the record's `extra`.
- **Off without a password:** with no `OPS_DB_PASSWORD` nothing is installed, and the service logs to stderr as before.

This is the minimal version of OBS-02. A redaction filter for payloads is Milestone 4; today's services log IDs,
offsets and error classes, never event bodies.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
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
    def __init__(self, service: str, writer: Writer, *, capacity: int = 1000, batch: int = 50) -> None:
        super().__init__()
        if capacity < 1 or batch < 1:
            raise ValueError("capacity and batch must be at least 1")
        self.service, self.writer, self.batch = service, writer, batch
        self.stats = SinkStats()
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=capacity)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

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
        """Write what is queued, in batches. Returns how many rows were taken off the queue."""
        taken = 0
        while True:
            rows: list[dict[str, Any]] = []
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
                self.stats.stored += len(rows)
            except Exception:  # a database failure costs these lines, not the service
                self.stats.dropped_failed += len(rows)

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
