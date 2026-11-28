"""Helpers for the posting service's real-stack tests: a real ledger over HTTP, producers, consumers, row counts."""

from __future__ import annotations

import socket
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import uvicorn
from confluent_kafka import Consumer, KafkaException, Producer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroDeserializer
from confluent_kafka.serialization import MessageField, SerializationContext
from sqlalchemy import Engine, text

from app.ledger.api import create_app
from app.ledger.core import LedgerSettings
from app.ledger.store import PostgresCreditStore
from app.pipeline import kafka_auth, schemas, topics
from app.pipeline.ledger_client import LedgerClient, LedgerTransient
from app.pipeline.posting import (
    DeadLetterPublisher,
    Outcome,
    PostingConfig,
    PostingConsumer,
    PostingService,
    PostingStore,
    make_consumer,
)
from app.pipeline.producer import CheckoutProducer, make_checkout_producer
from app.pipeline.retry import ParkedStore, RetryConfig, RetryWorker
from tests.infra import admin_kafka


@contextmanager
def ledger_server(engine: Engine, token: str) -> Iterator[str]:
    """The real ledger app (FastAPI + Postgres store) served over HTTP on a free local port, for one test."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    app = create_app(PostgresCreditStore(engine), LedgerSettings(token=token, rate_per_sec=10_000, burst=10_000))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise AssertionError("the ledger test server did not start")
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def checkout_producer(kafka: str, registry: SchemaRegistryClient, topic: str) -> CheckoutProducer:
    # The real delivery settings (ADR-0017): a test whose events weren't all delivered fails at the send, loudly.
    # As the broker's admin: the producer's own identity may write the real checkout topic only (ADR-0020).
    producer = make_checkout_producer(kafka, principal=kafka_auth.ADMIN)
    return CheckoutProducer(producer, registry, topic, schema=schemas.latest(topics.CHECKED_OUT))


def raw_producer(kafka: str) -> Producer:
    return Producer(admin_kafka(kafka))


def make_service(
    engine: Engine,
    ledger_url: str,
    token: str,
    kafka: str,
    registry: SchemaRegistryClient,
    output_topic: str,
    dlq_topic: str,
    fault: Callable[[str], None] | None = None,
    wrap: Callable[[Any], Any] | None = None,
) -> PostingService:
    ledger: Any = LedgerClient(ledger_url, token, timeout=5.0)
    return PostingService(
        PostingStore(engine, output_topic),
        wrap(ledger) if wrap else ledger,
        avro_deserialize(registry),
        DeadLetterPublisher(Producer({**admin_kafka(kafka), "acks": "all"}), dlq_topic),
        PostingConfig(output_topic=output_topic, dlq_topic=dlq_topic, park_base=0.02, park_cap=0.1),
        fault=fault,
    )


def avro_deserialize(registry: SchemaRegistryClient) -> Callable[[bytes, str], dict[str, Any]]:
    deserializer = AvroDeserializer(registry)

    def deserialize(value: bytes, topic: str) -> dict[str, Any]:
        record = deserializer(value, SerializationContext(topic, MessageField.VALUE))
        if not isinstance(record, dict):
            raise ValueError("not a record")
        return record

    return deserialize


class FlakyLedger:
    """The real ledger client, except that chosen stays fail transiently a set number of times first."""

    def __init__(self, real: Any, failures: dict[str, int]) -> None:
        self.real, self.left, self.lock = real, dict(failures), threading.Lock()

    def credit(self, key: str, member_number: str, stay_id: str, points: int, correlation_id: str) -> Any:
        with self.lock:
            if self.left.get(stay_id, 0) > 0:
                self.left[stay_id] -= 1
                raise LedgerTransient("unavailable_503")
        return self.real.credit(key, member_number, stay_id, points, correlation_id)


def make_worker(
    db: dict[str, Engine],
    ledger: tuple[str, str],
    kafka: str,
    registry: SchemaRegistryClient,
    scratch: dict[str, str],
    *,
    worker_id: str = "w1",
    fault: Callable[[str], None] | None = None,
    wrap: Callable[[Any], Any] | None = None,
    **config: Any,
) -> RetryWorker:
    url, token = ledger
    client: Any = LedgerClient(url, token, timeout=5.0)
    settings = {"backoff_base": 0.02, "backoff_cap": 0.1, **config}
    return RetryWorker(
        ParkedStore(db["posting"]),
        PostingStore(db["posting"], scratch["output"]),
        wrap(client) if wrap else client,
        avro_deserialize(registry),
        DeadLetterPublisher(Producer({**admin_kafka(kafka), "acks": "all"}), scratch["dlq"]),
        RetryConfig(worker_id=worker_id, **settings),
        fault=fault,
    )


def open_parked(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text("SELECT count(*) FROM parked_event WHERE status IN ('pending', 'in_flight')")
            ).scalar_one()
        )


def drain_parked(workers: Any, db: dict[str, Engine], timeout: float = 60.0) -> None:
    workers = workers if isinstance(workers, list) else [workers]
    deadline = time.monotonic() + timeout
    while open_parked(db["posting"]):
        if time.monotonic() > deadline:
            raise AssertionError(f"parked events still open after {timeout} s")
        for worker in workers:
            worker.run_once()
        time.sleep(0.02)


def first_claim(worker: RetryWorker, timeout: float = 10.0) -> Any:
    """Run cycles until one claims a parked event, and return that cycle (a fault hook's exception passes through).

    A parked event is due only `park_base / 2` or more after it was parked (10 ms here), so a single `run_once()`
    straight after parking can claim nothing on a fast machine. A test that needs the worker to reach a fault point
    must wait for the claim (found in CI, 2026-11-27: "DID NOT RAISE RetryCrash"). Never claiming is a failure."""
    deadline = time.monotonic() + timeout
    while True:
        cycle = worker.run_once()
        if cycle.claimed:
            return cycle
        if time.monotonic() > deadline:
            raise AssertionError(f"the worker claimed no parked event within {timeout} s")
        time.sleep(0.005)


def parked_rows(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(text("SELECT * FROM parked_event ORDER BY id"))]


def make_loop(service: PostingService, kafka: str, group: str, input_topic: str) -> PostingConsumer:
    return PostingConsumer(
        service,
        make_consumer(kafka, group, [input_topic], principal=kafka_auth.ADMIN),
        sleep=lambda s: time.sleep(min(s, 0.2)),
    )


def run_until(loop: PostingConsumer, wanted: int, timeout: float = 60.0) -> list[Outcome]:
    """Poll until `wanted` messages were handled (POSTED, DUPLICATE or DEAD_LETTERED). RETRY isn't counted."""
    outcomes: list[Outcome] = []
    deadline = time.monotonic() + timeout
    while len([o for o in outcomes if o is not Outcome.RETRY]) < wanted:
        if time.monotonic() > deadline:
            raise AssertionError(f"only {outcomes} within {timeout} s")
        outcome = loop.run_once(timeout=0.5)
        if outcome is not None:
            outcomes.append(outcome)
    return outcomes


def counts(engine: Engine, topic: str | None = None) -> tuple[int, int]:
    """(posting rows, outbox rows) as the posting service role sees them."""
    with engine.connect() as conn:
        postings = conn.execute(text("SELECT count(*) FROM posting")).scalar_one()
        query = "SELECT count(*) FROM outbox" + (" WHERE topic = :topic" if topic else "")
        outbox_rows = conn.execute(text(query), {"topic": topic} if topic else {}).scalar_one()
    return int(postings), int(outbox_rows)


def read_raw(kafka: str, topic: str, at_least: int, timeout: float = 30.0) -> list[Any]:
    """Raw messages (no decoding) from a topic, reading 2 s past `at_least` so late duplicates are seen."""
    consumer = Consumer(
        {**admin_kafka(kafka), "group.id": f"test-raw-{uuid.uuid4().hex[:8]}", "auto.offset.reset": "earliest"}
    )
    consumer.subscribe([topic])
    got, deadline, grace = [], time.monotonic() + timeout, None
    try:
        while time.monotonic() < (grace or deadline):
            message = consumer.poll(0.5)
            if message is not None and message.error() is None:
                got.append(message)
            if grace is None and len(got) >= at_least:
                grace = time.monotonic() + 2.0
    except KafkaException:
        pass
    finally:
        consumer.close()
    return got
