"""The posting service: consumes `stay.checked_out`, credits the ledger, writes posting + outbox (ADR-0015).

    python -m app.pipeline.posting      # in Docker Compose: the `posting` service

For each message:
1. Decode (Avro, via the registry) and validate. Anything that can never post is dead-lettered at once: undecodable,
   unknown schema version, a bad field, a correction (until PR-C), or a ledger 409 or other 4xx (until B2b counts
   attempts). The original bytes go to the DLQ topic with the failure headers of RFC-0001 D8.
2. Skip it if this event, or this stay revision, is already posted.
3. Credit the ledger with the business key `stay_id:revision`. The ledger is a separate system of record. Its
   UNIQUE(idempotency_key) gives every retry the same entry back, so it is outside the transaction on purpose.
4. **One Postgres transaction** inserts the posting row (`ON CONFLICT DO NOTHING`) and, only if that row is new, the
   outbox row for `points.posted`, carrying the trace context. Both commit, or neither does.
5. Commit the Kafka offset, **only after** step 4 committed (synchronous commit of exactly this message).

If the database fails, the dead-letter topic can't be reached, or (in B2a) the ledger fails transiently, the offset
isn't committed. The consumer seeks back to the same message and retries after a growing, jittered wait, so that
partition waits. B2b parks transient ledger failures instead.
"""

from __future__ import annotations

import logging
import os
import random
import signal
import sys
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from confluent_kafka import Consumer, KafkaError, TopicPartition
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from sqlalchemy import Engine, exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from app.pipeline import topics, trace
from app.pipeline.events import InvalidEvent, StayEvent, ledger_key, points_for, validate
from app.pipeline.ledger_client import LedgerClient, LedgerPermanent, LedgerTransient
from app.pipeline.tables import outbox, posting

log = logging.getLogger("posting")


class Outcome(StrEnum):
    POSTED = "posted"
    DUPLICATE = "duplicate"
    DEAD_LETTERED = "dead_lettered"
    RETRY = "retry"


class DatabaseFailure(Exception):
    """The posting transaction failed: nothing was written; the message is retried."""


class DeadLetterFailure(Exception):
    """The dead-letter topic didn't take the message: the offset isn't committed; the message is retried."""


class PostingCrash(Exception):
    """Raised by a test's fault hook to stop the service at an exact point, as a crash would."""


@dataclass(frozen=True)
class IncomingMessage:
    topic: str
    partition: int
    offset: int
    key: bytes | None
    value: bytes | None
    headers: dict[str, str]

    @classmethod
    def from_kafka(cls, message: Any) -> IncomingMessage:
        headers = {}
        for name, raw in message.headers() or []:
            headers[name] = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw or "")
        return cls(message.topic(), message.partition(), message.offset(), message.key(), message.value(), headers)


@dataclass(frozen=True)
class PostingConfig:
    output_topic: str = topics.POINTS_POSTED
    dlq_topic: str = topics.DLQ
    retry_base: float = 0.5
    retry_cap: float = 10.0


# ---------- dead letters ----------


class DeadLetterPublisher:
    """Copies the original message (bytes, key, headers) to the DLQ topic with why it failed. Waits for delivery."""

    def __init__(self, producer: Any, topic: str, timeout: float = 10.0) -> None:
        self.producer, self.topic, self.timeout = producer, topic, timeout

    def publish(self, message: IncomingMessage, error_class: str, detail: str, attempts: int = 1) -> None:
        now = datetime.now(UTC).isoformat()
        headers = {
            **message.headers,
            "error_class": error_class,
            "error_detail": detail[:300],
            "attempt": str(attempts),
            "original_topic": message.topic,
            "original_partition": str(message.partition),
            "original_offset": str(message.offset),
            "first_failed_at": now,
            "last_failed_at": now,
        }
        result: dict[str, KafkaError | None] = {}

        def delivered(error: KafkaError | None, _message: Any) -> None:
            result["error"] = error

        self.producer.produce(
            self.topic, key=message.key, value=message.value, headers=list(headers.items()), on_delivery=delivered
        )
        self.producer.flush(self.timeout)
        if "error" not in result or result["error"] is not None:
            raise DeadLetterFailure(f"dead letter not delivered: {result.get('error', 'timeout')}")


# ---------- metrics ----------


class PostingMetrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.outcomes = Counter("posting_events", "Messages handled, by outcome", ["outcome"], registry=self.registry)
        self.dead_letters = Counter(
            "posting_dlq_messages", "Messages sent to the dead-letter topic", ["error_class"], registry=self.registry
        )
        self.retries = Counter("posting_retries", "Messages retried in place", ["reason"], registry=self.registry)
        self.ledger_seconds = Histogram(
            "posting_ledger_request_seconds", "Ledger credit latency", registry=self.registry
        )

    def render(self) -> bytes:
        return generate_latest(self.registry)


# ---------- the posting database ----------


class Store(Protocol):
    def already_posted(self, event: StayEvent) -> bool: ...

    def write(
        self,
        event: StayEvent,
        entry_id: str,
        trace_context: Mapping[str, str],
        fault: Callable[[str], None] | None = None,
    ) -> bool: ...


def outbox_payload(event: StayEvent, entry_id: str, now: datetime | None = None) -> dict[str, Any]:
    """The `points.posted` record. Its `event_id` is fixed here, so a re-published outbox row keeps it."""
    points = points_for(event)
    return {
        "event_id": str(uuid.uuid4()),
        "source_event_id": event.event_id,
        "ledger_entry_id": entry_id,
        "tenant": event.tenant,
        "member_number": event.member_number,
        "stay_id": event.stay_id,
        "revision": event.revision,
        "stay_points": points,
        "credited_points": points,  # revision 1 only: the whole stay (corrections credit a difference, PR-C)
        "posted_at": int((now or datetime.now(UTC)).timestamp() * 1000),
        "correlation_id": event.correlation_id,
    }


class PostingStore:
    """Runs as `posting_app`: SELECT and INSERT on `posting` and `outbox`, nothing else."""

    def __init__(self, engine: Engine, output_topic: str = topics.POINTS_POSTED) -> None:
        self.engine, self.output_topic = engine, output_topic

    def already_posted(self, event: StayEvent) -> bool:
        """This event, or this stay revision under another event ID, has a posting row."""
        same = (posting.c.event_id == event.event_id) | (
            (posting.c.stay_id == event.stay_id) & (posting.c.revision == event.revision)
        )
        try:
            with self.engine.connect() as conn:
                return bool(conn.execute(select(exists().where(same))).scalar())
        except SQLAlchemyError as exc:
            raise DatabaseFailure(type(exc).__name__) from exc

    def write(
        self,
        event: StayEvent,
        entry_id: str,
        trace_context: Mapping[str, str],
        fault: Callable[[str], None] | None = None,
    ) -> bool:
        """The one transaction: the posting row and, only if it is new, its outbox row. Returns whether it was new."""
        points = points_for(event)
        try:
            with self.engine.begin() as conn:
                new = conn.execute(
                    insert(posting)
                    .values(
                        event_id=event.event_id,
                        stay_id=event.stay_id,
                        revision=event.revision,
                        member_number=event.member_number,
                        stay_points=points,
                        credited_points=points,
                        ledger_entry_id=entry_id,
                        correlation_id=event.correlation_id,
                    )
                    .on_conflict_do_nothing()  # any unique key: event_id, or (stay_id, revision)
                    .returning(posting.c.event_id)
                ).first()
                if fault is not None:
                    fault("mid_transaction")
                if new is None:
                    return False
                conn.execute(
                    insert(outbox).values(
                        topic=self.output_topic,
                        message_key=event.member_number,
                        payload=outbox_payload(event, entry_id),
                        headers={
                            "correlation_id": event.correlation_id,
                            "schema_version": "1",
                            "source_event_id": event.event_id,
                        },
                        trace_context=dict(trace_context),
                    )
                )
            return True
        except SQLAlchemyError as exc:
            raise DatabaseFailure(type(exc).__name__) from exc


# ---------- the service ----------


@dataclass
class PostingService:
    store: Store
    ledger: Any  # LedgerClient, or a fake with .credit() in the unit tests
    deserialize: Callable[[bytes, str], dict[str, Any]]
    dead_letters: Any  # DeadLetterPublisher, or a fake with .publish()
    config: PostingConfig = field(default_factory=PostingConfig)
    metrics: PostingMetrics = field(default_factory=PostingMetrics)
    fault: Callable[[str], None] | None = None  # tests only: "after_ledger_credit", "mid_transaction", ...

    def _fault(self, point: str) -> None:
        if self.fault is not None:
            self.fault(point)

    def handle(self, message: IncomingMessage) -> Outcome:
        outcome = self._handle(message)
        self.metrics.outcomes.labels(outcome=outcome.value).inc()
        return outcome

    def _handle(self, message: IncomingMessage) -> Outcome:
        try:
            if message.value is None:
                raise InvalidEvent("schema", "empty message")
            try:
                record = self.deserialize(message.value, message.topic)
            except Exception as exc:  # any decoding failure: the bytes can never become an event
                raise InvalidEvent("schema", f"{type(exc).__name__}: {exc}") from exc
            event = validate(record, message.headers)
        except InvalidEvent as invalid:
            return self._dead_letter(message, invalid.code, invalid.detail)

        if self.store.already_posted(event):
            return Outcome.DUPLICATE
        try:
            with self.metrics.ledger_seconds.time():
                credit = self.ledger.credit(
                    ledger_key(event), event.member_number, event.stay_id, points_for(event), event.correlation_id
                )
        except LedgerPermanent as refused:
            return self._dead_letter(message, f"ledger_{refused.reason}", str(refused))
        self._fault("after_ledger_credit")
        incoming = trace.context_from_headers(message.headers)
        context = {**incoming, "traceparent": trace.child(incoming.get("traceparent"))}  # this service's span
        inserted = self.store.write(event, credit.entry_id, context, fault=self.fault)
        return Outcome.POSTED if inserted else Outcome.DUPLICATE

    def _dead_letter(self, message: IncomingMessage, error_class: str, detail: str) -> Outcome:
        self.dead_letters.publish(message, error_class, detail)
        self.metrics.dead_letters.labels(error_class=error_class).inc()
        log.warning("dead-lettered %s/%s@%s: %s", message.topic, message.partition, message.offset, error_class)
        return Outcome.DEAD_LETTERED


# ---------- the consumer loop ----------


def make_consumer(bootstrap: str, group_id: str, subscribe: list[str]) -> Consumer:
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap.replace("localhost", "127.0.0.1"),
            "group.id": group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,  # offsets are committed by hand, after the database transaction
            "enable.auto.offset.store": False,
        }
    )
    consumer.subscribe(subscribe)
    return consumer


RETRYABLE = (DatabaseFailure, DeadLetterFailure, LedgerTransient)


class PostingConsumer:
    def __init__(
        self,
        service: Any,
        consumer: Any,
        *,
        sleep: Callable[[float], None] = time.sleep,
        rand: Callable[[], float] = random.random,
    ) -> None:
        self.service, self.consumer, self.sleep, self.rand = service, consumer, sleep, rand
        self.consecutive_failures = 0

    def _fault(self, point: str) -> None:
        fault = getattr(self.service, "fault", None)
        if fault is not None:
            fault(point)

    def run_once(self, timeout: float = 1.0) -> Outcome | None:
        message = self.consumer.poll(timeout)
        if message is None:
            return None
        if message.error() is not None:
            log.warning("consumer error: %s", message.error())
            return None
        incoming = IncomingMessage.from_kafka(message)
        try:
            outcome: Outcome = self.service.handle(incoming)
        except RETRYABLE as failure:
            # Nothing committed: go back to this same message and try again after a growing, jittered wait.
            self.consumer.seek(TopicPartition(incoming.topic, incoming.partition, incoming.offset))
            self.consecutive_failures += 1
            config = getattr(self.service, "config", PostingConfig())
            step = min(config.retry_cap, config.retry_base * 2 ** (self.consecutive_failures - 1))
            self.sleep(step / 2 + self.rand() * step / 2)
            metrics = getattr(self.service, "metrics", None)
            if metrics is not None:
                metrics.retries.labels(reason=type(failure).__name__).inc()
            return Outcome.RETRY
        self._fault("after_db_commit_before_offset_commit")
        self.consumer.commit(message=message, asynchronous=False)
        self.consecutive_failures = 0
        return outcome

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self.run_once()
            except PostingCrash:
                raise
            except Exception:  # an unexpected error: log it and keep consuming (nothing was committed)
                log.exception("posting cycle failed")
                stop.wait(1.0)


def main() -> int:
    from confluent_kafka import Producer
    from confluent_kafka.schema_registry import SchemaRegistryClient
    from confluent_kafka.schema_registry.avro import AvroDeserializer
    from confluent_kafka.serialization import MessageField, SerializationContext
    from dotenv import load_dotenv
    from prometheus_client import start_http_server
    from sqlalchemy import create_engine

    from app.db.roles import Database, runtime_url

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
    bootstrap = env.get("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092")
    deserializer = AvroDeserializer(
        SchemaRegistryClient({"url": env.get("SCHEMA_REGISTRY_URL", "http://127.0.0.1:8081")})
    )

    def deserialize(value: bytes, topic: str) -> dict[str, Any]:
        record = deserializer(value, SerializationContext(topic, MessageField.VALUE))
        if not isinstance(record, dict):
            raise ValueError("not a record")
        return record

    service = PostingService(
        PostingStore(engine),
        LedgerClient(env.get("LEDGER_API_URL", "http://127.0.0.1:8020"), env.get("LEDGER_API_TOKEN", "")),
        deserialize,
        DeadLetterPublisher(Producer({"bootstrap.servers": bootstrap, "acks": "all"}), topics.DLQ),
    )
    loop = PostingConsumer(
        service, make_consumer(bootstrap, env.get("POSTING_GROUP_ID", "posting-service"), [topics.CHECKED_OUT])
    )
    start_http_server(
        int(env.get("POSTING_METRICS_PORT", "9109")),
        addr=env.get("POSTING_METRICS_HOST", "127.0.0.1"),
        registry=service.metrics.registry,
    )
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())  # graceful: finish the message, commit, close (DEL-01)
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    log.info("posting service started")
    loop.run(stop)
    loop.consumer.close()
    log.info("posting service stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
