"""Kafka and the Karapace schema registry, for real (RFC-0001 D1-D4, D7; spec J "publish/consume").

Needs TEST_KAFKA_BOOTSTRAP_SERVERS and TEST_SCHEMA_REGISTRY_URL (scripts\\test_integration.ps1 sets them). Each test
uses its own throwaway topics and subjects, deleted afterwards, so the stack's topics are only read.
This proves on day one the RFC's main risk: that confluent-kafka's registry client works unchanged against Karapace.
"""

from __future__ import annotations

import contextlib
import json
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from confluent_kafka import Consumer, Producer
from confluent_kafka.admin import AdminClient
from confluent_kafka.schema_registry import ConfigCompatibilityLevel, Schema, SchemaRegistryClient, ServerConfig
from confluent_kafka.schema_registry.avro import AvroDeserializer, AvroSerializer
from confluent_kafka.schema_registry.error import SchemaRegistryError
from confluent_kafka.serialization import MessageField, SerializationContext

from app.pipeline import schemas, topics

pytestmark = pytest.mark.kafka


@pytest.fixture(scope="session")
def bootstrap() -> str:
    servers = os.environ.get("TEST_KAFKA_BOOTSTRAP_SERVERS")
    if not servers:
        pytest.skip(
            "TEST_KAFKA_BOOTSTRAP_SERVERS is not set: run scripts\\stack.ps1 up, then scripts\\test_integration.ps1"
        )
    return servers


@pytest.fixture(scope="session")
def registry() -> SchemaRegistryClient:
    url = os.environ.get("TEST_SCHEMA_REGISTRY_URL")
    if not url:
        pytest.skip(
            "TEST_SCHEMA_REGISTRY_URL is not set: run scripts\\stack.ps1 up, then scripts\\test_integration.ps1"
        )
    return SchemaRegistryClient({"url": url})


@pytest.fixture
def scratch_topic(bootstrap: str) -> Iterator[str]:
    name = f"test.{uuid.uuid4().hex[:12]}"
    yield name
    AdminClient({"bootstrap.servers": bootstrap}).delete_topics([name], operation_timeout=30)


def stay_record() -> dict[str, object]:
    return {
        "event_id": str(uuid.uuid4()),
        # Avro logical types come back as Python dates and times, so the record is written with them too.
        "occurred_at": datetime(2026, 11, 17, 12, tzinfo=UTC),
        "tenant": "hg-demo",
        "property": "beach-resort",
        "stay_id": "BR-0001",
        "member_number": "GR-00001",
        "revision": 1,
        "check_in": date(2026, 11, 14),
        "check_out": date(2026, 11, 17),
        "nights": 3,
        "room_rate_cents": 45_000,
        "taxes_cents": 5_400,
        "fees_cents": 3_000,
        "currency": "USD",
        "correlation_id": "corr-kafka-1",
    }


def test_the_stack_has_every_pipeline_topic_with_three_partitions(bootstrap):
    metadata = AdminClient({"bootstrap.servers": bootstrap}).list_topics(timeout=30)
    for spec in topics.TOPICS:
        assert spec.name in metadata.topics, f"{spec.name} missing: did kafka-init run?"
        assert len(metadata.topics[spec.name].partitions) == spec.partitions


def test_ensure_topics_creates_only_what_is_missing(bootstrap, scratch_topic):
    spec = (topics.TopicSpec(scratch_topic, partitions=2),)
    assert topics.ensure_topics(bootstrap, spec) == [scratch_topic]
    assert topics.ensure_topics(bootstrap, spec) == []


def test_an_avro_event_round_trips_through_kafka_and_karapace(bootstrap, registry, scratch_topic):
    topics.ensure_topics(bootstrap, (topics.TopicSpec(scratch_topic),))
    schema = schemas.latest(topics.CHECKED_OUT)
    serialize = AvroSerializer(registry, schema)
    record = stay_record()
    producer = Producer({"bootstrap.servers": bootstrap, "enable.idempotence": True, "acks": "all"})
    delivered: list[object] = []
    producer.produce(
        scratch_topic,
        key=str(record["member_number"]).encode(),
        value=serialize(record, SerializationContext(scratch_topic, MessageField.VALUE)),
        headers={"correlation_id": str(record["correlation_id"]).encode()},
        on_delivery=lambda err, msg: delivered.append(err or msg),
    )
    producer.flush(30)
    assert len(delivered) == 1 and not isinstance(delivered[0], Exception)

    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": f"test-{uuid.uuid4().hex[:8]}",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,  # D-semantics: commit after processing, never before
        }
    )
    consumer.subscribe([scratch_topic])
    try:
        message = None
        for _ in range(60):
            message = consumer.poll(1.0)
            if message is not None and message.error() is None:
                break
        assert message is not None and message.error() is None, "no message within 60 s"
        value = AvroDeserializer(registry)(message.value(), SerializationContext(scratch_topic, MessageField.VALUE))
        assert value == record
        assert message.key() == b"GR-00001"
        assert dict(message.headers() or [])["correlation_id"] == b"corr-kafka-1"
        consumer.commit(message=message, asynchronous=False)
    finally:
        consumer.close()
        drop_subject(registry, f"{scratch_topic}-value")


def test_the_registry_enforces_backward_transitive_compatibility(registry):
    subject = f"test-{uuid.uuid4().hex[:12]}-value"
    v1 = schemas.latest(topics.CHECKED_OUT)
    try:
        level = ConfigCompatibilityLevel(schemas.COMPATIBILITY)
        registry.set_config(subject, ServerConfig(compatibility=level))
        assert registry.get_config(subject).compatibility_level == level  # GET /config answers "compatibilityLevel"
        registry.register_schema(subject, Schema(v1, "AVRO"))

        compatible = json.loads(v1)
        compatible["fields"].append({"name": "loyalty_note", "type": ["null", "string"], "default": None})
        breaking = json.loads(v1)
        breaking["fields"].append({"name": "required_new", "type": "string"})  # no default: old data can't be read

        assert registry.test_compatibility(subject, Schema(json.dumps(compatible), "AVRO")) is True
        assert registry.test_compatibility(subject, Schema(json.dumps(breaking), "AVRO")) is False
    finally:
        drop_subject(registry, subject)


def drop_subject(registry: SchemaRegistryClient, subject: str) -> None:
    """Soft then hard delete. A subject that was never registered is fine: cleanup must not hide the real error."""
    for permanent in (False, True):
        with contextlib.suppress(SchemaRegistryError):
            registry.delete_subject(subject, permanent=permanent)
