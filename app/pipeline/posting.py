"""The posting service: consumes `stay.checked_out`, credits the ledger, writes posting + outbox (ADR-0015).

    python -m app.pipeline.posting      # in Docker Compose: the `posting` service

For each message:
1. Decode (Avro, via the registry) and validate. Anything that can never post is dead-lettered at once: undecodable,
   unknown schema version, a bad field, or a ledger 409 (the stay revision was credited with different points). The
   original bytes go to the DLQ topic with the failure headers of RFC-0001 D8.
2. Skip it if this event, or this stay revision, is already posted, or this event is already parked (a redelivery).
3. If the member has parked events, **park this one behind them** (ADR-0016). Per-member order holds without
   blocking the partition.
4. Plan the credit from the stay's latest posted revision (D10, `events.plan_credit`):
   - an original: the stay's points; a correction: the signed difference from the latest posted revision
   - a revision at or below the latest posted one: recorded in `skipped_event`, not credited (outcome SKIPPED)
   - a correction with nothing posted for its stay: parked as `original_missing`, retried, dead-lettered at the max
5. Credit the ledger with the business key `stay_id:revision`. The ledger is a separate system of record. Its
   UNIQUE(idempotency_key) gives every retry the same entry back, so it is outside the transaction on purpose.
   - A transient failure (5xx, timeout, 429, 401) parks the event; it never counts toward dead-lettering.
   - Another 4xx parks it with `attempts = 1`. The retry worker dead-letters it at the maximum.
6. **One Postgres transaction** inserts the posting row (`ON CONFLICT DO NOTHING`) and, only if that row is new, the
   outbox row for `points.posted`, carrying the trace context. Both commit, or neither does. When the retry worker
   posts a parked event, marking it `done` is part of the same transaction.
7. Commit the Kafka offset, **only after** step 6 (or the park, or the skip) committed: a synchronous commit of
   exactly this message.

If the database fails, or the dead-letter topic can't be reached, the offset isn't committed. Parking needs the
database too. The consumer seeks back to the same message and retries after a growing, jittered wait, so that
partition waits.
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

from confluent_kafka import Consumer, KafkaError, KafkaException, TopicPartition
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from sqlalchemy import Engine, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from app.ops import logsink
from app.pipeline import topics, trace
from app.pipeline.events import (
    CreditKind,
    CreditPlan,
    InvalidEvent,
    LatestPosting,
    StayEvent,
    ledger_key,
    plan_credit,
    points_for,
    validate,
)
from app.pipeline.ledger_client import LedgerClient, LedgerPermanent, LedgerTransient
from app.pipeline.tables import PARKED_OPEN, outbox, parked_event, posting, skipped_event

log = logging.getLogger("posting")


class Outcome(StrEnum):
    POSTED = "posted"
    DUPLICATE = "duplicate"
    DEAD_LETTERED = "dead_lettered"
    PARKED = "parked"
    SKIPPED = "skipped"  # a stale stay revision: recorded, not credited (D10)
    RETRY = "retry"


class DatabaseFailure(Exception):
    """The posting transaction failed: nothing was written; the message is retried."""


class DeadLetterFailure(Exception):
    """The dead-letter topic didn't take the message: the offset isn't committed; the message is retried."""


class PostingCrash(Exception):
    """Raised by a test's fault hook to stop the service at an exact point, as a crash would."""


class LeaseLost(Exception):
    """A retry worker's claim on a parked event ran out and someone else holds it: its transaction is rolled back."""


@dataclass(frozen=True)
class ParkReason:
    kind: str  # behind (waiting for the member's earlier event) | transient | permanent
    error_class: str | None = None
    detail: str | None = None


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
    retry_base: float = 0.5  # seek-back retries (database or DLQ topic down)
    retry_cap: float = 10.0
    park_base: float = 1.0  # first retry of a parked event after a failure
    park_cap: float = 60.0


# ---------- dead letters ----------


class DeadLetterPublisher:
    """Copies the original message (bytes, key, headers) to the DLQ topic with why it failed. Waits for delivery."""

    def __init__(self, producer: Any, topic: str, timeout: float = 10.0) -> None:
        self.producer, self.topic, self.timeout = producer, topic, timeout

    def publish(
        self,
        message: IncomingMessage,
        error_class: str,
        detail: str,
        attempts: int = 1,
        first_failed_at: str | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        headers = {
            **message.headers,
            "error_class": error_class,
            "error_detail": detail[:300],
            "attempt": str(attempts),
            "original_topic": message.topic,
            "original_partition": str(message.partition),
            "original_offset": str(message.offset),
            "first_failed_at": first_failed_at or now,
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
        self.parked = Counter("posting_parked", "Events parked, by reason", ["reason"], registry=self.registry)
        self.commit_failures = Counter(
            "posting_offset_commit_failures",
            "Offset commits that failed after the work committed",
            ["error"],
            registry=self.registry,
        )
        self.ledger_seconds = Histogram(
            "posting_ledger_request_seconds", "Ledger credit latency", registry=self.registry
        )

    def render(self) -> bytes:
        return generate_latest(self.registry)


# ---------- the posting database ----------


class Store(Protocol):
    def already_posted(self, event: StayEvent) -> bool: ...

    def already_parked(self, event_id: str) -> bool: ...

    def member_has_parked(self, member_number: str) -> bool: ...

    def park(self, message: IncomingMessage, event: StayEvent, reason: ParkReason, delay: float) -> bool: ...

    def latest_posting(self, stay_id: str) -> LatestPosting | None: ...

    def record_skipped(self, event: StayEvent, plan: CreditPlan) -> bool: ...

    def write(
        self,
        event: StayEvent,
        entry_id: str,
        trace_context: Mapping[str, str],
        fault: Callable[[str], None] | None = None,
        parked: tuple[str, int] | None = None,
        credited: int | None = None,
    ) -> bool: ...


def outbox_payload(
    event: StayEvent, entry_id: str, now: datetime | None = None, credited: int | None = None
) -> dict[str, Any]:
    """The `points.posted` record. Its `event_id` is fixed here, so a re-published outbox row keeps it.
    `credited` is what the ledger got: the whole stay for an original, the difference for a correction (D10)."""
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
        "credited_points": points if credited is None else credited,
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
        return self._exists(same)

    def already_parked(self, event_id: str) -> bool:
        return self._exists(parked_event.c.event_id == event_id)

    def member_has_parked(self, member_number: str) -> bool:
        return self._exists((parked_event.c.member_number == member_number) & parked_event.c.status.in_(PARKED_OPEN))

    def latest_posting(self, stay_id: str) -> LatestPosting | None:
        """The stay's highest posted revision and the points it earns, or None if nothing is posted for it."""
        try:
            with self.engine.connect() as conn:
                row = conn.execute(
                    select(posting.c.revision, posting.c.stay_points)
                    .where(posting.c.stay_id == stay_id)
                    .order_by(posting.c.revision.desc())
                    .limit(1)
                ).first()
        except SQLAlchemyError as exc:
            raise DatabaseFailure(type(exc).__name__) from exc
        return None if row is None else LatestPosting(int(row.revision), int(row.stay_points))

    def record_skipped(self, event: StayEvent, plan: CreditPlan) -> bool:
        """Record a stale revision (once per event ID). False if this event was recorded before (a redelivery)."""
        try:
            with self.engine.begin() as conn:
                row = conn.execute(
                    insert(skipped_event)
                    .values(
                        event_id=event.event_id,
                        stay_id=event.stay_id,
                        revision=event.revision,
                        member_number=event.member_number,
                        reason="stale_revision",
                        latest_revision=plan.latest_revision,
                        correlation_id=event.correlation_id,
                    )
                    .on_conflict_do_nothing(index_elements=["event_id"])
                    .returning(skipped_event.c.event_id)
                ).first()
        except SQLAlchemyError as exc:
            raise DatabaseFailure(type(exc).__name__) from exc
        return row is not None

    def _exists(self, condition: Any) -> bool:
        try:
            with self.engine.connect() as conn:
                return bool(conn.execute(select(exists().where(condition))).scalar())
        except SQLAlchemyError as exc:
            raise DatabaseFailure(type(exc).__name__) from exc

    def park(self, message: IncomingMessage, event: StayEvent, reason: ParkReason, delay: float) -> bool:
        """Park the event (its original bytes too), due after `delay` seconds. False if it was already parked."""
        failed = reason.kind != "behind"
        now = func.now()
        try:
            with self.engine.begin() as conn:
                row = conn.execute(
                    insert(parked_event)
                    .values(
                        event_id=event.event_id,
                        member_number=event.member_number,
                        stay_id=event.stay_id,
                        revision=event.revision,
                        raw_key=message.key,
                        raw_value=message.value,
                        raw_headers=dict(message.headers),
                        source_topic=message.topic,
                        source_partition=message.partition,
                        source_offset=message.offset,
                        attempts=1 if reason.kind == "permanent" else 0,
                        transient_failures=1 if reason.kind == "transient" else 0,
                        next_attempt_at=now + func.make_interval(0, 0, 0, 0, 0, 0, delay),
                        error_class=reason.error_class,
                        last_error=(reason.detail or "")[:300] or None,
                        first_failed_at=now if failed else None,
                        last_failed_at=now if failed else None,
                    )
                    .on_conflict_do_nothing(index_elements=["event_id"])
                    .returning(parked_event.c.id)
                ).first()
            return row is not None
        except SQLAlchemyError as exc:
            raise DatabaseFailure(type(exc).__name__) from exc

    def write(
        self,
        event: StayEvent,
        entry_id: str,
        trace_context: Mapping[str, str],
        fault: Callable[[str], None] | None = None,
        parked: tuple[str, int] | None = None,
        credited: int | None = None,
    ) -> bool:
        """The one transaction: the posting row; only if it is new, its outbox row; and with `parked`
        (worker ID, parked event ID), that parked event marked done. Returns whether the posting was new.
        A worker whose claim was taken over raises LeaseLost, and nothing is written.
        `credited`: what the ledger was asked for (the difference for a correction); default the stay's points."""
        points = points_for(event)
        credited = points if credited is None else credited
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
                        credited_points=credited,
                        ledger_entry_id=entry_id,
                        correlation_id=event.correlation_id,
                    )
                    .on_conflict_do_nothing()  # any unique key: event_id, or (stay_id, revision)
                    .returning(posting.c.event_id)
                ).first()
                if fault is not None:
                    fault("mid_transaction")
                if parked is not None:
                    worker_id, parked_id = parked
                    marked = conn.execute(
                        update(parked_event)
                        .where(
                            (parked_event.c.id == parked_id)
                            & (parked_event.c.status == "in_flight")
                            & (parked_event.c.claimed_by == worker_id)
                        )
                        .values(status="done", done_at=func.now(), lease_until=None)
                    ).rowcount
                    if marked != 1:
                        raise LeaseLost(f"parked event {parked_id} is no longer claimed by {worker_id}")
                if new is None:
                    return False
                conn.execute(
                    insert(outbox).values(
                        topic=self.output_topic,
                        message_key=event.member_number,
                        payload=outbox_payload(event, entry_id, credited=credited),
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

        if self.store.already_posted(event) or self.store.already_parked(event.event_id):
            return Outcome.DUPLICATE
        if self.store.member_has_parked(event.member_number):
            return self._park(message, event, ParkReason("behind"), delay=0.0)
        plan = plan_credit(event, self.store.latest_posting(event.stay_id))
        if plan.kind == CreditKind.STALE:
            if not self.store.record_skipped(event, plan):
                return Outcome.DUPLICATE
            log.info("skipped stale revision %s of %s (latest %s)", event.revision, event.stay_id, plan.latest_revision)
            return Outcome.SKIPPED
        if plan.kind == CreditKind.ORIGINAL_MISSING:
            reason = ParkReason("permanent", "original_missing", f"no posting for {event.stay_id} yet")
            return self._park(message, event, reason, self._first_delay(None))
        try:
            with self.metrics.ledger_seconds.time():
                credit = self.ledger.credit(
                    ledger_key(event), event.member_number, event.stay_id, plan.credited_points, event.correlation_id
                )
        except LedgerTransient as unavailable:
            reason = ParkReason("transient", f"ledger_{unavailable.reason}", str(unavailable))
            return self._park(message, event, reason, self._first_delay(unavailable.retry_after))
        except LedgerPermanent as refused:
            if refused.reason == "idempotency_conflict":  # retrying can't fix a key used with other points
                return self._dead_letter(message, f"ledger_{refused.reason}", str(refused))
            reason = ParkReason("permanent", f"ledger_{refused.reason}", str(refused))
            return self._park(message, event, reason, self._first_delay(None))
        self._fault("after_ledger_credit")
        incoming = trace.context_from_headers(message.headers)
        context = {**incoming, "traceparent": trace.child(incoming.get("traceparent"))}  # this service's span
        inserted = self.store.write(event, credit.entry_id, context, fault=self.fault, credited=plan.credited_points)
        return Outcome.POSTED if inserted else Outcome.DUPLICATE

    def _first_delay(self, retry_after: float | None) -> float:
        step = self.config.park_base
        return max(retry_after or 0.0, step / 2 + random.random() * step / 2)  # noqa: S311 (jitter, not security)

    def _park(self, message: IncomingMessage, event: StayEvent, reason: ParkReason, delay: float) -> Outcome:
        if not self.store.park(message, event, reason, delay):
            return Outcome.DUPLICATE  # parked by an earlier delivery of this same event
        self.metrics.parked.labels(reason=reason.kind).inc()
        return Outcome.PARKED

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
        try:
            self.consumer.commit(message=message, asynchronous=False)
        except KafkaException as exc:
            # The work is done (its transaction committed), so this is not a retry. Offsets are cumulative per
            # partition: the next successful commit covers this one. If none comes (a crash or a rebalance), the
            # message is redelivered and recognised as a duplicate. Seen in M2 PR-B2b: "Waiting for coordinator".
            error = exc.args[0] if exc.args and isinstance(exc.args[0], KafkaError) else None
            name = error.name() if error is not None else type(exc).__name__
            log.warning(
                "offset commit failed for %s/%s@%s: %s", incoming.topic, incoming.partition, incoming.offset, name
            )
            metrics = getattr(self.service, "metrics", None)
            if metrics is not None:
                metrics.commit_failures.labels(error=name).inc()
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
    logsink.install("posting")  # stored log lines for the investigator; off without OPS_DB_PASSWORD
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
