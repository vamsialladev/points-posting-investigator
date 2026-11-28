"""The outbox relay: publishes committed outbox rows to Kafka, at least once, in order per member (ADR-0014).

    python -m app.pipeline.relay        # in Docker Compose: the `relay` service

One cycle:
1. **Claim** (one short transaction): up to `batch_size` due rows, each the OLDEST open row of its member, with
   `FOR UPDATE SKIP LOCKED`; mark them `in_flight` with this relay's ID and a lease. Several relays can run: a row is
   locked by one claim only, and a member's younger row is never claimable while an older one is open, so
   per-member order holds across relays.
2. **Publish** each row (Avro via the schema registry), with trace context and IDs in the headers; wait for delivery.
3. **Mark**: delivered rows become `published`; failed rows go back to `pending` with a backoff, or to `dead`.
   The mark only applies while this relay still holds the claim (`claimed_by`, `in_flight`).

Delivery is at least once. A relay that dies after publishing and before marking leaves rows `in_flight`; when the
lease runs out another relay publishes them again, so `points.posted` can carry a duplicate. Readers dedupe on
`event_id`. Nothing that reads `points.posted` writes to the ledger.

Failures:
- **transient** (broker unreachable, delivery timeout, full local queue): retried after a short delay with jitter,
  and never counted toward dead-lettering. A Kafka outage is not a poison message. The relay also stops claiming while
  the broker is unreachable, so an outage doesn't churn leases.
- **permanent** (serialization, message too large, anything unknown): counted in `attempts`, retried with exponential
  backoff, and dead-lettered (`status='dead'`) at `max_attempts`. A dead row unblocks its member's later rows. Dead
  rows are never replayed automatically (that's M7, with approval).
"""

from __future__ import annotations

import logging
import os
import random
import signal
import socket
import sys
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from confluent_kafka import KafkaError, KafkaException, Producer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroSerializer
from confluent_kafka.serialization import MessageField, SerializationContext, SerializationError
from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest
from sqlalchemy import Engine, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.types import BigInteger

from app.ops import logsink
from app.pipeline import kafka_auth, trace

log = logging.getLogger("relay")


# ---------- rules (pure) ----------


class ErrorClass(StrEnum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"


_TRANSIENT_CODES = {
    getattr(KafkaError, name)
    for name in (
        "_MSG_TIMED_OUT",
        "_TIMED_OUT",
        "_TRANSPORT",
        "_ALL_BROKERS_DOWN",
        "_QUEUE_FULL",
        "REQUEST_TIMED_OUT",
        "NETWORK_EXCEPTION",
        "LEADER_NOT_AVAILABLE",
        "NOT_LEADER_FOR_PARTITION",
        "NOT_ENOUGH_REPLICAS",
    )
    if hasattr(KafkaError, name)
}


def classify(error: BaseException | KafkaError) -> ErrorClass:
    if isinstance(error, KafkaException) and error.args and isinstance(error.args[0], KafkaError):
        error = error.args[0]
    if isinstance(error, KafkaError):
        return ErrorClass.TRANSIENT if error.retriable() or error.code() in _TRANSIENT_CODES else ErrorClass.PERMANENT
    if isinstance(error, BufferError):
        return ErrorClass.TRANSIENT
    return ErrorClass.PERMANENT


def backoff_delay(attempt: int, base: float, cap: float, rand: Callable[[], float] = random.random) -> float:
    """Exponential with "equal jitter": between half and all of min(cap, base * 2^(attempt-1))."""
    if attempt < 1:
        raise ValueError("attempt starts at 1")
    step = min(cap, base * float(2 ** (attempt - 1)))
    return step / 2 + rand() * step / 2


@dataclass(frozen=True)
class RelayConfig:
    relay_id: str
    batch_size: int = 50
    lease_seconds: float = 30.0
    max_attempts: int = 5
    backoff_base: float = 1.0
    backoff_cap: float = 60.0
    delivery_timeout: float = 10.0

    def __post_init__(self) -> None:
        if not self.relay_id:
            raise ValueError("relay_id is required")
        if self.batch_size < 1 or self.max_attempts < 1:
            raise ValueError("batch_size and max_attempts must be at least 1")
        if self.lease_seconds <= 0 or self.backoff_base <= 0 or self.delivery_timeout <= 0:
            raise ValueError("lease_seconds, backoff_base and delivery_timeout must be positive")


def failure_outcome(attempts: int, error_class: ErrorClass, config: RelayConfig) -> tuple[str, int]:
    """(new status, new attempts) after a failed publish. Only permanent failures count toward dead-lettering."""
    if error_class is ErrorClass.TRANSIENT:
        return "pending", attempts
    attempts += 1
    return ("dead" if attempts >= config.max_attempts else "pending"), attempts


def describe(error: BaseException | KafkaError) -> str:
    """For `last_error`: the error's class and a short message. The payload is never included."""
    if isinstance(error, KafkaError):
        return f"KafkaError {error.name()}: {error.str()}"[:300]
    return f"{type(error).__name__}: {error}"[:300]


# ---------- data ----------


@dataclass(frozen=True)
class ClaimedRow:
    id: int
    topic: str
    message_key: str
    payload: dict[str, Any]
    headers: dict[str, str]
    trace_context: dict[str, str]
    attempts: int


@dataclass(frozen=True)
class Failure:
    row_id: int
    error_class: ErrorClass
    detail: str
    attempts: int = 0  # the row's attempts before this failure


@dataclass(frozen=True)
class OutboxStats:
    unpublished: int
    dead: int
    oldest_unpublished_age_seconds: float


@dataclass(frozen=True)
class CycleResult:
    claimed: int = 0
    published: int = 0
    failed: int = 0
    dead: int = 0
    skipped_broker_down: bool = False


class RelayCrash(Exception):
    """Raised by a test's fault hook to stop a relay at an exact point, as a crash would."""


# ---------- the outbox, in Postgres ----------

_CLAIM = text(
    """
    WITH candidates AS (
        SELECT o.id
        FROM outbox o
        WHERE ((o.status = 'pending' AND o.next_attempt_at <= now())
            OR (o.status = 'in_flight' AND o.lease_until < now()))
          AND NOT EXISTS (
              SELECT 1 FROM outbox older
              WHERE older.message_key = o.message_key
                AND older.id < o.id
                AND older.status IN ('pending', 'in_flight'))
        ORDER BY o.id
        LIMIT :limit
        FOR UPDATE SKIP LOCKED
    )
    UPDATE outbox
    SET status = 'in_flight', claimed_by = :relay_id, lease_until = now() + make_interval(secs => :lease)
    FROM candidates
    WHERE outbox.id = candidates.id
    RETURNING outbox.id, outbox.topic, outbox.message_key, outbox.payload, outbox.headers, outbox.trace_context,
              outbox.attempts
    """
)

_PUBLISHED = text(
    """
    UPDATE outbox SET status = 'published', published_at = now(), lease_until = NULL
    WHERE id = ANY(:ids) AND status = 'in_flight' AND claimed_by = :relay_id
    """
).bindparams(bindparam("ids", type_=ARRAY(BigInteger)))

_FAILED = text(
    """
    UPDATE outbox
    SET status = CAST(:status AS text),
        attempts = :attempts,
        last_error = :error,
        next_attempt_at = now() + make_interval(secs => :delay),
        dead_at = CASE WHEN CAST(:status AS text) = 'dead' THEN now() END,
        claimed_by = CASE WHEN CAST(:status AS text) = 'dead' THEN claimed_by END,
        lease_until = NULL
    WHERE id = :id AND status = 'in_flight' AND claimed_by = :relay_id
    """
)

_STATS = text(
    """
    SELECT count(*) FILTER (WHERE status IN ('pending', 'in_flight')) AS unpublished,
           count(*) FILTER (WHERE status = 'dead') AS dead,
           COALESCE(EXTRACT(EPOCH FROM now() - min(created_at) FILTER (WHERE status IN ('pending', 'in_flight'))), 0)
               AS oldest
    FROM outbox
    """
)


class Store(Protocol):
    def claim(self, relay_id: str, limit: int, lease_seconds: float) -> list[ClaimedRow]: ...
    def mark_published(self, relay_id: str, ids: list[int]) -> int: ...
    def mark_failed(self, relay_id: str, failures: list[Failure], config: RelayConfig) -> int: ...
    def stats(self) -> OutboxStats: ...


class OutboxStore:
    """Runs as the `posting_relay` role: it can read the outbox and change only the delivery columns."""

    def __init__(self, engine: Engine, rand: Callable[[], float] = random.random) -> None:
        self.engine = engine
        self.rand = rand

    def claim(self, relay_id: str, limit: int, lease_seconds: float) -> list[ClaimedRow]:
        with self.engine.begin() as conn:
            rows = conn.execute(_CLAIM, {"limit": limit, "relay_id": relay_id, "lease": lease_seconds}).all()
        return sorted((ClaimedRow(**row._mapping) for row in rows), key=lambda r: r.id)

    def mark_published(self, relay_id: str, ids: list[int]) -> int:
        if not ids:
            return 0
        with self.engine.begin() as conn:
            return conn.execute(_PUBLISHED, {"ids": ids, "relay_id": relay_id}).rowcount

    def mark_failed(self, relay_id: str, failures: list[Failure], config: RelayConfig) -> int:
        changed = 0
        with self.engine.begin() as conn:
            for failure in failures:
                status, attempts = failure_outcome(failure.attempts, failure.error_class, config)
                # Transient: a short delay (the broker check stops claims during an outage). Permanent: exponential.
                delay = backoff_delay(max(1, attempts), config.backoff_base, config.backoff_cap, self.rand)
                changed += conn.execute(
                    _FAILED,
                    {
                        "status": status,
                        "attempts": attempts,
                        "error": failure.detail,
                        "delay": delay,
                        "id": failure.row_id,
                        "relay_id": relay_id,
                    },
                ).rowcount
        return changed

    def stats(self) -> OutboxStats:
        with self.engine.connect() as conn:
            row = conn.execute(_STATS).one()
        return OutboxStats(int(row.unpublished), int(row.dead), float(row.oldest))


# ---------- Kafka side ----------


def make_producer(bootstrap: str, delivery_timeout: float, principal: str = kafka_auth.RELAY) -> Producer:
    return Producer(
        {
            **kafka_auth.client_config(principal, bootstrap),
            "enable.idempotence": True,  # no duplicates from the producer's own retries within a session
            "acks": "all",
            "message.timeout.ms": int(delivery_timeout * 1000),  # a failed delivery is reported, not retried forever
            "linger.ms": 5,
        }
    )


class AvroPayloadSerializer:
    """Serializes an outbox payload with its topic's committed schema. Any failure is a SerializationError."""

    def __init__(self, registry: SchemaRegistryClient, schema_by_topic: Mapping[str, str]) -> None:
        self._serializers = {topic: AvroSerializer(registry, schema) for topic, schema in schema_by_topic.items()}

    def __call__(self, topic: str, payload: dict[str, Any]) -> bytes:
        serializer = self._serializers.get(topic)
        if serializer is None:
            raise SerializationError(f"no schema configured for topic {topic!r}")
        try:
            value: bytes | None = serializer(payload, SerializationContext(topic, MessageField.VALUE))
        except SerializationError:
            raise
        except Exception as exc:  # fastavro reports a bad record as ValueError, TypeError, ...
            raise SerializationError(f"{type(exc).__name__}: {exc}") from exc
        if value is None:
            raise SerializationError("serializer returned nothing")
        return value


class RelayMetrics:
    """Prometheus metrics, one registry per relay (scraped from /metrics; dashboards and alert rules come in M4)."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.unpublished = Gauge("outbox_unpublished_rows", "Outbox rows not yet published", registry=self.registry)
        self.dead = Gauge("outbox_dead_rows", "Dead-lettered outbox rows", registry=self.registry)
        self.oldest = Gauge(
            "outbox_oldest_unpublished_age_seconds",
            "Age of the oldest unpublished row (outbox lag)",
            registry=self.registry,
        )
        self.published = Counter("outbox_published", "Rows published by this relay", registry=self.registry)
        self.failures = Counter("outbox_publish_failures", "Failed publishes", ["error_class"], registry=self.registry)
        self.dead_lettered = Counter("outbox_dead_lettered", "Rows this relay dead-lettered", registry=self.registry)

    def observe(self, stats: OutboxStats) -> None:
        self.unpublished.set(stats.unpublished)
        self.dead.set(stats.dead)
        self.oldest.set(stats.oldest_unpublished_age_seconds)

    def render(self) -> bytes:
        return generate_latest(self.registry)


# ---------- the loop ----------


@dataclass
class Relay:
    store: Store
    producer: Any  # confluent_kafka.Producer, or a fake with produce / flush / list_topics in the unit tests
    serializer: Callable[[str, dict[str, Any]], bytes]
    config: RelayConfig
    metrics: RelayMetrics = field(default_factory=RelayMetrics)
    fault: Callable[[str], None] | None = None  # tests only: raise RelayCrash at "after_claim" / "after_publish..."
    before_produce: Callable[[ClaimedRow], None] | None = None  # tests only: inject a failure for one row

    def _fault(self, point: str) -> None:
        if self.fault is not None:
            self.fault(point)

    def broker_available(self) -> bool:
        try:
            self.producer.list_topics(timeout=2)
            return True
        except KafkaException:
            return False

    def run_once(self) -> CycleResult:
        if not self.broker_available():
            self.metrics.observe(self.store.stats())
            return CycleResult(skipped_broker_down=True)
        rows = self.store.claim(self.config.relay_id, self.config.batch_size, self.config.lease_seconds)
        self._fault("after_claim")
        if not rows:
            self.metrics.observe(self.store.stats())
            return CycleResult()

        outcomes: dict[int, BaseException | KafkaError | None] = {}

        def delivered(row_id: int) -> Callable[[KafkaError | None, Any], None]:
            def callback(error: KafkaError | None, _message: Any) -> None:
                outcomes[row_id] = error

            return callback

        for row in rows:
            try:
                if self.before_produce is not None:
                    self.before_produce(row)
                value = self.serializer(row.topic, row.payload)
                headers = {
                    **row.headers,
                    "event_id": str(row.payload.get("event_id", "")),
                    "outbox_id": str(row.id),
                    **trace.kafka_headers(row.trace_context),
                }
                self.producer.produce(
                    row.topic,
                    key=row.message_key.encode(),
                    value=value,
                    headers=list(headers.items()),
                    on_delivery=delivered(row.id),
                )
            except Exception as exc:  # recorded per row; the other rows still go out
                outcomes[row.id] = exc
        self.producer.flush(self.config.delivery_timeout + 5)
        for row in rows:  # no delivery report in time counts as a timeout
            outcomes.setdefault(row.id, KafkaError(KafkaError._MSG_TIMED_OUT))
        self._fault("after_publish_before_mark")

        by_id = {row.id: row for row in rows}
        published = sorted(row_id for row_id, error in outcomes.items() if error is None)
        failures = [
            Failure(row_id, classify(error), describe(error), by_id[row_id].attempts)
            for row_id, error in sorted(outcomes.items(), key=lambda item: item[0])
            if error is not None
        ]
        self.store.mark_published(self.config.relay_id, published)
        self.store.mark_failed(self.config.relay_id, failures, self.config)

        dead = sum(failure_outcome(f.attempts, f.error_class, self.config)[0] == "dead" for f in failures)
        self.metrics.published.inc(len(published))
        for failure in failures:
            self.metrics.failures.labels(error_class=failure.error_class.value).inc()
        self.metrics.dead_lettered.inc(dead)
        self.metrics.observe(self.store.stats())
        if failures:
            log.warning("relay %s: %d failed (%d dead-lettered)", self.config.relay_id, len(failures), dead)
        return CycleResult(len(rows), len(published), len(failures), dead)

    def run(self, stop: threading.Event, poll_interval: float = 0.5) -> None:
        """Cycle until `stop` is set. After a cycle with nothing to do, wait `poll_interval`."""
        while not stop.is_set():
            try:
                result = self.run_once()
            except RelayCrash:
                raise
            except Exception:  # a database or broker hiccup: log it, wait, try again
                log.exception("relay %s: cycle failed", self.config.relay_id)
                stop.wait(poll_interval)
                continue
            if result.claimed == 0:
                stop.wait(poll_interval)


def main() -> int:
    from dotenv import load_dotenv
    from prometheus_client import start_http_server
    from sqlalchemy import create_engine

    from app.db.roles import Database, runtime_url
    from app.pipeline import schemas, topics

    load_dotenv(override=False)
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    logsink.install("relay")  # stored log lines for the investigator; off without OPS_DB_PASSWORD
    env = os.environ
    database = Database("posting", env.get("DB_PREFIX", ""))
    engine = create_engine(
        runtime_url(
            database,
            env.get("RELAY_DB_PASSWORD", ""),
            host=env.get("POSTGRES_HOST", "localhost"),
            port=int(env.get("POSTGRES_PORT", "5432")),
            role="relay",
        ),
        pool_pre_ping=True,
    )
    config = RelayConfig(relay_id=env.get("RELAY_ID", socket.gethostname()))
    registry = SchemaRegistryClient({"url": env.get("SCHEMA_REGISTRY_URL", "http://localhost:8081")})
    relay = Relay(
        OutboxStore(engine),
        make_producer(env.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"), config.delivery_timeout),
        AvroPayloadSerializer(registry, {topics.POINTS_POSTED: schemas.latest(topics.POINTS_POSTED)}),
        config,
    )
    start_http_server(
        int(env.get("RELAY_METRICS_PORT", "9108")),
        addr=env.get("RELAY_METRICS_HOST", "127.0.0.1"),
        registry=relay.metrics.registry,
    )
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())  # graceful: finish the cycle, then exit (DEL-01)
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    log.info("relay %s started", config.relay_id)
    relay.run(stop)
    relay.producer.flush(10)
    log.info("relay %s stopped", config.relay_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
