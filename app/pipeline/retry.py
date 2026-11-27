"""The retry worker: posts parked events in arrival order per member, or dead-letters them (ADR-0016).

    python -m app.pipeline.retry        # in Docker Compose: the `retry-worker` service

One cycle:
1. **Claim**, in one short transaction: due parked events, each the OLDEST open one of its member, with
   `FOR UPDATE SKIP LOCKED`. Each is marked `in_flight` with this worker's ID and a lease. Several workers can run.
   A member's later events wait until the earlier one is `done` or `dead`, so per-member order holds.
2. **Retry** each one from its stored original bytes: decode, validate, skip if it's posted meanwhile, credit the
   ledger (same business key, so a retry gets the same entry back).
3. **Success:** the posting row, its outbox row, and this parked event's change to `done` commit in one transaction.
   It's fenced on the claim: a worker whose lease ran out rolls back.
4. **Failure:**
   - **transient** (ledger 5xx, timeout, 429, 401): `transient_failures` + 1, exponential backoff with jitter,
     **never dead-lettered**. An outage isn't poison, and it shows as the oldest parked age.
   - **permanent** (other ledger 4xx): `attempts` + 1 and backoff. At `max_attempts` the original bytes go to the DLQ
     topic (attempt N, the real first-failure time), and only then is the event marked `dead`.
   - **conflict** (ledger 409) or undecodable: dead-lettered at once.

A worker that dies mid-way leaves its claims `in_flight`. Another worker takes them once the lease runs out. Dead
events are never replayed automatically (M7, with approval).
"""

from __future__ import annotations

import logging
import os
import random
import signal
import socket
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.pipeline import trace
from app.pipeline.events import InvalidEvent, ledger_key, points_for, validate
from app.pipeline.ledger_client import LedgerPermanent, LedgerTransient
from app.pipeline.posting import DatabaseFailure, DeadLetterFailure, IncomingMessage, LeaseLost
from app.pipeline.relay import backoff_delay

log = logging.getLogger("retry")


class FailureKind(StrEnum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    CONFLICT = "conflict"  # ledger 409 or an event that can't be decoded: no retry can fix it


@dataclass(frozen=True)
class RetryConfig:
    worker_id: str
    batch_size: int = 20
    lease_seconds: float = 30.0
    max_attempts: int = 5
    backoff_base: float = 1.0
    backoff_cap: float = 60.0

    def __post_init__(self) -> None:
        if not self.worker_id:
            raise ValueError("worker_id is required")
        if self.batch_size < 1 or self.max_attempts < 1:
            raise ValueError("batch_size and max_attempts must be at least 1")
        if self.lease_seconds <= 0 or self.backoff_base <= 0:
            raise ValueError("lease_seconds and backoff_base must be positive")


def parked_failure_outcome(
    attempts: int, transient: int, kind: FailureKind, config: RetryConfig
) -> tuple[str, int, int, int]:
    """(status, attempts, transient_failures, backoff step) after a failed retry."""
    if kind is FailureKind.TRANSIENT:
        return "pending", attempts, transient + 1, transient + 1
    attempts += 1
    if kind is FailureKind.CONFLICT or attempts >= config.max_attempts:
        return "dead", attempts, transient, attempts
    return "pending", attempts, transient, attempts


@dataclass(frozen=True)
class ParkedRow:
    id: int
    event_id: str
    member_number: str
    raw_key: bytes | None
    raw_value: bytes
    raw_headers: dict[str, str]
    source_topic: str
    source_partition: int
    source_offset: int
    attempts: int
    transient_failures: int
    first_failed_at: datetime | None

    def message(self) -> IncomingMessage:
        return IncomingMessage(
            self.source_topic,
            self.source_partition,
            self.source_offset,
            self.raw_key,
            self.raw_value,
            dict(self.raw_headers),
        )


@dataclass(frozen=True)
class ParkedStats:
    open: int
    dead: int
    oldest_open_age_seconds: float


@dataclass(frozen=True)
class RetryCycle:
    claimed: int = 0
    posted: int = 0
    parked_again: int = 0
    dead: int = 0


class RetryCrash(Exception):
    """Raised by a test's fault hook to stop the worker at an exact point, as a crash would."""


# ---------- parked events, in Postgres ----------

_CLAIM = text(
    """
    WITH candidates AS (
        SELECT p.id
        FROM parked_event p
        WHERE ((p.status = 'pending' AND p.next_attempt_at <= now())
            OR (p.status = 'in_flight' AND p.lease_until < now()))
          AND NOT EXISTS (
              SELECT 1 FROM parked_event older
              WHERE older.member_number = p.member_number
                AND older.id < p.id
                AND older.status IN ('pending', 'in_flight'))
        ORDER BY p.id
        LIMIT :limit
        FOR UPDATE SKIP LOCKED
    )
    UPDATE parked_event
    SET status = 'in_flight', claimed_by = :worker, lease_until = now() + make_interval(secs => :lease)
    FROM candidates
    WHERE parked_event.id = candidates.id
    RETURNING parked_event.id, parked_event.event_id, parked_event.member_number, parked_event.raw_key,
              parked_event.raw_value, parked_event.raw_headers, parked_event.source_topic,
              parked_event.source_partition, parked_event.source_offset, parked_event.attempts,
              parked_event.transient_failures, parked_event.first_failed_at
    """
)

_FAILED = text(
    """
    UPDATE parked_event
    SET status = CAST(:status AS text),
        attempts = :attempts,
        transient_failures = :transient,
        error_class = :error_class,
        last_error = :detail,
        first_failed_at = COALESCE(first_failed_at, now()),
        last_failed_at = now(),
        next_attempt_at = now() + make_interval(secs => :delay),
        dead_at = CASE WHEN CAST(:status AS text) = 'dead' THEN now() END,
        claimed_by = CASE WHEN CAST(:status AS text) = 'dead' THEN claimed_by END,
        lease_until = NULL
    WHERE id = :id AND status = 'in_flight' AND claimed_by = :worker
    """
)

_DONE = text(
    """
    UPDATE parked_event SET status = 'done', done_at = now(), lease_until = NULL
    WHERE id = :id AND status = 'in_flight' AND claimed_by = :worker
    """
)

_STATS = text(
    """
    SELECT count(*) FILTER (WHERE status IN ('pending', 'in_flight')) AS open,
           count(*) FILTER (WHERE status = 'dead') AS dead,
           COALESCE(EXTRACT(EPOCH FROM now() - min(parked_at) FILTER (WHERE status IN ('pending', 'in_flight'))), 0)
               AS oldest
    FROM parked_event
    """
)


class Parked(Protocol):
    def claim(self, worker_id: str, limit: int, lease_seconds: float) -> list[ParkedRow]: ...
    def mark_failed(
        self,
        worker_id: str,
        row: ParkedRow,
        status: str,
        attempts: int,
        transient: int,
        error_class: str,
        detail: str,
        delay: float,
    ) -> int: ...
    def mark_done(self, worker_id: str, row: ParkedRow) -> int: ...
    def stats(self) -> ParkedStats: ...


class ParkedStore:
    """Runs as `posting_app`, which may change only the delivery columns of `parked_event` and never deletes one."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def claim(self, worker_id: str, limit: int, lease_seconds: float) -> list[ParkedRow]:
        with self.engine.begin() as conn:
            rows = conn.execute(_CLAIM, {"limit": limit, "worker": worker_id, "lease": lease_seconds}).all()
        return sorted((ParkedRow(**row._mapping) for row in rows), key=lambda r: r.id)

    def mark_failed(
        self,
        worker_id: str,
        row: ParkedRow,
        status: str,
        attempts: int,
        transient: int,
        error_class: str,
        detail: str,
        delay: float,
    ) -> int:
        params = {
            "status": status,
            "attempts": attempts,
            "transient": transient,
            "error_class": error_class,
            "detail": detail[:300],
            "delay": delay,
            "id": row.id,
            "worker": worker_id,
        }
        with self.engine.begin() as conn:
            return conn.execute(_FAILED, params).rowcount

    def mark_done(self, worker_id: str, row: ParkedRow) -> int:
        with self.engine.begin() as conn:
            return conn.execute(_DONE, {"id": row.id, "worker": worker_id}).rowcount

    def stats(self) -> ParkedStats:
        with self.engine.connect() as conn:
            row = conn.execute(_STATS).one()
        return ParkedStats(int(row.open), int(row.dead), float(row.oldest))


class RetryMetrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.open = Gauge("posting_parked_open", "Parked events waiting (pending or in flight)", registry=self.registry)
        self.dead = Gauge("posting_parked_dead", "Parked events dead-lettered", registry=self.registry)
        self.oldest = Gauge(
            "posting_parked_oldest_age_seconds", "Age of the oldest open parked event", registry=self.registry
        )
        self.outcomes = Counter("retry_outcomes", "Retries, by outcome", ["outcome"], registry=self.registry)

    def observe(self, stats: ParkedStats) -> None:
        self.open.set(stats.open)
        self.dead.set(stats.dead)
        self.oldest.set(stats.oldest_open_age_seconds)

    def render(self) -> bytes:
        return generate_latest(self.registry)


# ---------- the worker ----------


@dataclass
class RetryWorker:
    parked: Parked
    postings: Any  # posting.PostingStore (already_posted, write), or a fake
    ledger: Any  # LedgerClient, or a fake
    deserialize: Callable[[bytes, str], dict[str, Any]]
    dead_letters: Any  # posting.DeadLetterPublisher, or a fake
    config: RetryConfig
    metrics: RetryMetrics = field(default_factory=RetryMetrics)
    fault: Callable[[str], None] | None = None  # tests only: "after_ledger_credit", "mid_transaction"
    rand: Callable[[], float] = random.random

    def _fault(self, point: str) -> None:
        if self.fault is not None:
            self.fault(point)

    def run_once(self) -> RetryCycle:
        rows = self.parked.claim(self.config.worker_id, self.config.batch_size, self.config.lease_seconds)
        posted = again = dead = 0
        for row in rows:
            try:
                outcome = self._retry(row)
            except (DatabaseFailure, LeaseLost, DeadLetterFailure, SQLAlchemyError) as exc:
                # Nothing is marked; the lease runs out and this or another worker tries again.
                log.warning("parked event %s left for its lease to expire: %s", row.id, type(exc).__name__)
                outcome = "left"
            self.metrics.outcomes.labels(outcome=outcome).inc()
            posted += outcome == "posted"
            again += outcome == "pending"
            dead += outcome == "dead"
        self.metrics.observe(self.parked.stats())
        return RetryCycle(len(rows), posted, again, dead)

    def _retry(self, row: ParkedRow) -> str:
        message = row.message()
        try:
            event = validate(self.deserialize(row.raw_value, row.source_topic), message.headers)
        except InvalidEvent as invalid:
            return self._fail(row, FailureKind.CONFLICT, invalid.code, invalid.detail)
        except Exception as exc:  # undecodable bytes can never become an event
            return self._fail(row, FailureKind.CONFLICT, "schema", f"{type(exc).__name__}: {exc}")
        if self.postings.already_posted(event):
            self.parked.mark_done(self.config.worker_id, row)
            return "done"
        try:
            credit = self.ledger.credit(
                ledger_key(event), event.member_number, event.stay_id, points_for(event), event.correlation_id
            )
        except LedgerTransient as unavailable:
            return self._fail(
                row, FailureKind.TRANSIENT, f"ledger_{unavailable.reason}", str(unavailable), unavailable.retry_after
            )
        except LedgerPermanent as refused:
            kind = FailureKind.CONFLICT if refused.reason == "idempotency_conflict" else FailureKind.PERMANENT
            return self._fail(row, kind, f"ledger_{refused.reason}", str(refused))
        self._fault("after_ledger_credit")
        incoming = trace.context_from_headers(message.headers)
        context = {**incoming, "traceparent": trace.child(incoming.get("traceparent"))}
        self.postings.write(event, credit.entry_id, context, fault=self.fault, parked=(self.config.worker_id, row.id))
        return "posted"

    def _fail(
        self, row: ParkedRow, kind: FailureKind, error_class: str, detail: str, retry_after: float | None = None
    ) -> str:
        status, attempts, transient, step = parked_failure_outcome(
            row.attempts, row.transient_failures, kind, self.config
        )
        if status == "dead":
            # The DLQ copy first: if it can't be delivered, nothing is marked and the event is tried again.
            first = row.first_failed_at.isoformat() if row.first_failed_at else None
            self.dead_letters.publish(row.message(), error_class, detail, attempts=attempts, first_failed_at=first)
        delay = max(
            retry_after or 0.0, backoff_delay(step, self.config.backoff_base, self.config.backoff_cap, self.rand)
        )
        self.parked.mark_failed(self.config.worker_id, row, status, attempts, transient, error_class, detail, delay)
        if status == "dead":
            log.warning("parked event %s dead-lettered after %d attempt(s): %s", row.id, attempts, error_class)
        return status

    def run(self, stop: threading.Event, poll_interval: float = 0.5) -> None:
        while not stop.is_set():
            try:
                cycle = self.run_once()
            except RetryCrash:
                raise
            except Exception:  # a database hiccup: log it, wait, try again
                log.exception("retry cycle failed")
                stop.wait(poll_interval)
                continue
            if cycle.claimed == 0:
                stop.wait(poll_interval)


def main() -> int:
    from confluent_kafka import Producer
    from confluent_kafka.schema_registry import SchemaRegistryClient
    from confluent_kafka.schema_registry.avro import AvroDeserializer
    from confluent_kafka.serialization import MessageField, SerializationContext
    from dotenv import load_dotenv
    from prometheus_client import start_http_server
    from sqlalchemy import create_engine

    from app.db.roles import Database, runtime_url
    from app.pipeline import topics
    from app.pipeline.ledger_client import LedgerClient
    from app.pipeline.posting import DeadLetterPublisher, PostingStore

    load_dotenv(override=False)
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    env = os.environ
    engine = create_engine(
        runtime_url(
            Database("posting", env.get("DB_PREFIX", "")),
            env.get("POSTING_DB_PASSWORD", ""),
            host=env.get("POSTGRES_HOST", "localhost"),
            port=int(env.get("POSTGRES_PORT", "5432")),
        ),
        pool_pre_ping=True,
    )
    deserializer = AvroDeserializer(
        SchemaRegistryClient({"url": env.get("SCHEMA_REGISTRY_URL", "http://127.0.0.1:8081")})
    )

    def deserialize(value: bytes, topic: str) -> dict[str, Any]:
        record = deserializer(value, SerializationContext(topic, MessageField.VALUE))
        if not isinstance(record, dict):
            raise ValueError("not a record")
        return record

    bootstrap = env.get("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092")
    worker = RetryWorker(
        ParkedStore(engine),
        PostingStore(engine),
        LedgerClient(env.get("LEDGER_API_URL", "http://127.0.0.1:8020"), env.get("LEDGER_API_TOKEN", "")),
        deserialize,
        DeadLetterPublisher(Producer({"bootstrap.servers": bootstrap, "acks": "all"}), topics.DLQ),
        RetryConfig(worker_id=env.get("RETRY_WORKER_ID", socket.gethostname())),
    )
    start_http_server(
        int(env.get("RETRY_METRICS_PORT", "9110")),
        addr=env.get("RETRY_METRICS_HOST", "127.0.0.1"),
        registry=worker.metrics.registry,
    )
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())  # graceful: finish the cycle, then exit
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    log.info("retry worker %s started", worker.config.worker_id)
    worker.run(stop)
    log.info("retry worker %s stopped", worker.config.worker_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
