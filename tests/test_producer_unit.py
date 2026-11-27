"""The checkout producer never reports success for an event Kafka didn't take (incident 2026-11-26, ADR-0017).

Offline, with a fake producer that delivers, fails or never answers. The real-broker versions are in
tests/test_producer_kafka.py.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from confluent_kafka import KafkaError, KafkaException

from app.pipeline.producer import CheckoutProducer, DeliveryFailed, build_event, checkout_producer_config


def record(member="GR-00001", stay="BR-0001"):
    return build_event(
        member_number=member,
        stay_id=stay,
        check_in=date(2026, 11, 14),
        nights=2,
        room_rate_cents=20_000,
        occurred_at=datetime(2026, 11, 17, tzinfo=UTC),
    )


class FakeProducer:
    """Delivers each message with the error chosen for its event (None = delivered); `silent` never reports."""

    def __init__(self, errors=None, silent=(), queued_after_flush=0, raise_on_produce=None):
        self.errors, self.silent, self.queued = errors or {}, set(silent), queued_after_flush
        self.raise_on_produce = raise_on_produce
        self.pending, self.sent = [], []

    def produce(self, topic, key, value, headers, on_delivery):
        if self.raise_on_produce is not None:
            raise self.raise_on_produce
        event_id = dict(headers)["event_id"]
        self.sent.append(event_id)
        self.pending.append((event_id, on_delivery))

    def flush(self, timeout):
        for event_id, callback in self.pending:
            if event_id not in self.silent:
                callback(self.errors.get(event_id), None)
        self.pending = []
        return self.queued


def producer(fake):
    return CheckoutProducer(fake, None, "stay.checked_out", serialize=lambda record, ctx: b"avro")


def test_a_delivered_event_is_a_success():
    fake = FakeProducer()
    rec = record()
    assert producer(fake).send(rec).event_id == rec["event_id"]


def test_an_event_the_broker_refuses_is_a_failure_the_caller_sees():
    rec = record()
    fake = FakeProducer(errors={rec["event_id"]: KafkaError(KafkaError.UNKNOWN_TOPIC_OR_PART)})
    with pytest.raises(DeliveryFailed) as failed:
        producer(fake).send(rec)
    assert failed.value.failed == [(rec["event_id"], "UNKNOWN_TOPIC_OR_PART")]
    assert rec["event_id"] in str(failed.value)


def test_a_delivery_timeout_is_a_failure_too():
    rec = record()
    fake = FakeProducer(errors={rec["event_id"]: KafkaError(KafkaError._MSG_TIMED_OUT)})
    with pytest.raises(DeliveryFailed) as failed:
        producer(fake).send(rec)
    assert failed.value.failed == [(rec["event_id"], "_MSG_TIMED_OUT")]


def test_messages_still_queued_after_the_flush_timeout_fail_loudly():
    rec = record()
    with pytest.raises(DeliveryFailed) as failed:
        producer(FakeProducer(silent={rec["event_id"]}, queued_after_flush=1)).send(rec)
    assert failed.value.undelivered == [rec["event_id"]] and failed.value.queued == 1


def test_an_event_with_no_report_at_all_is_not_assumed_delivered():
    rec = record()
    with pytest.raises(DeliveryFailed) as failed:
        producer(FakeProducer(silent={rec["event_id"]})).send(rec)  # flush said 0 queued, but nothing was reported
    assert failed.value.undelivered == [rec["event_id"]]


def test_a_batch_flush_names_every_failed_event_and_only_those():
    good, bad1, bad2 = record(stay="BR-0001"), record(stay="BR-0003"), record(stay="BR-0005")
    fake = FakeProducer(
        errors={
            bad1["event_id"]: KafkaError(KafkaError._MSG_TIMED_OUT),
            bad2["event_id"]: KafkaError(KafkaError._TRANSPORT),
        }
    )
    p = producer(fake)
    for rec in (good, bad1, bad2):
        p.send(rec, flush=False)
    with pytest.raises(DeliveryFailed) as failed:
        p.flush()
    assert sorted(failed.value.failed) == sorted(
        [(bad1["event_id"], "_MSG_TIMED_OUT"), (bad2["event_id"], "_TRANSPORT")]
    )
    p.flush()  # the failures were reported once; nothing is pending any more


def test_a_synchronous_produce_error_is_a_delivery_failure():
    fake = FakeProducer(raise_on_produce=KafkaException(KafkaError(KafkaError._UNKNOWN_TOPIC)))
    with pytest.raises(DeliveryFailed) as failed:
        producer(fake).send(record())
    assert failed.value.failed[0][1] == "_UNKNOWN_TOPIC"


def test_the_producer_settings_bound_retries_and_keep_per_partition_order():
    config = checkout_producer_config("localhost:9092", delivery_timeout=12.5)
    assert config["bootstrap.servers"] == "127.0.0.1:9092"
    assert config["enable.idempotence"] is True  # retries can't duplicate
    assert config["acks"] == "all"
    assert config["enable.gapless.guarantee"] is True  # a lost message fails the producer: no later one gets past it
    assert config["max.in.flight.requests.per.connection"] <= 5  # what idempotent ordering allows
    assert config["delivery.timeout.ms"] == 12_500  # retries stop here, and the caller is told


def test_the_delivery_timeout_must_be_positive():
    with pytest.raises(ValueError):
        checkout_producer_config("localhost:9092", delivery_timeout=0)
