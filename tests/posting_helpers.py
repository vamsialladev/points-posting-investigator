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
from app.pipeline import schemas, topics
from app.pipeline.ledger_client import LedgerClient
from app.pipeline.posting import (
    DeadLetterPublisher,
    Outcome,
    PostingConfig,
    PostingConsumer,
    PostingService,
    PostingStore,
    make_consumer,
)
from app.pipeline.producer import CheckoutProducer


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
    producer = Producer({"bootstrap.servers": kafka, "enable.idempotence": True, "acks": "all"})
    return CheckoutProducer(producer, registry, topic, schema=schemas.latest(topics.CHECKED_OUT))


def raw_producer(kafka: str) -> Producer:
    return Producer({"bootstrap.servers": kafka})


def make_service(
    engine: Engine,
    ledger_url: str,
    token: str,
    kafka: str,
    registry: SchemaRegistryClient,
    output_topic: str,
    dlq_topic: str,
    fault: Callable[[str], None] | None = None,
) -> PostingService:
    deserializer = AvroDeserializer(registry)

    def deserialize(value: bytes, topic: str) -> dict[str, Any]:
        record = deserializer(value, SerializationContext(topic, MessageField.VALUE))
        if not isinstance(record, dict):
            raise ValueError("not a record")
        return record

    return PostingService(
        PostingStore(engine, output_topic),
        LedgerClient(ledger_url, token, timeout=5.0),
        deserialize,
        DeadLetterPublisher(Producer({"bootstrap.servers": kafka, "acks": "all"}), dlq_topic),
        PostingConfig(output_topic=output_topic, dlq_topic=dlq_topic),
        fault=fault,
    )


def make_loop(service: PostingService, kafka: str, group: str, input_topic: str) -> PostingConsumer:
    return PostingConsumer(service, make_consumer(kafka, group, [input_topic]), sleep=lambda s: time.sleep(min(s, 0.2)))


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
        {"bootstrap.servers": kafka, "group.id": f"test-raw-{uuid.uuid4().hex[:8]}", "auto.offset.reset": "earliest"}
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
