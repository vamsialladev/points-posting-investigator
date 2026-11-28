"""The checkout producer against the real broker and registry (incident 2026-11-26, ADR-0017).

Before the fix, `CheckoutProducer.send()` returned normally for an event Kafka refused: it attached no delivery
callback, and `flush()` only counted queued messages (verification log, M2 PR-B2b). These tests fail on that code.
Not covered: an *unauthorised* topic, because the local broker has no ACLs; a refused topic is the same failure path
(a delivery report with an error).
"""

from __future__ import annotations

import collections
import time
import uuid
from datetime import date

import pytest
from confluent_kafka import Producer

from app.pipeline import kafka_auth, schemas, topics
from app.pipeline.producer import CheckoutProducer, DeliveryFailed, build_event, checkout_producer_config
from tests.kafka_proxy import KafkaReplyCutter
from tests.posting_helpers import read_raw

pytestmark = [pytest.mark.kafka, pytest.mark.postgres]  # postgres: the shared `scratch` fixture


def event(member: str = "GR-00001", n: int = 1) -> dict:
    return build_event(
        member_number=member, stay_id=f"BR-{n:04d}", check_in=date(2026, 11, 14), nights=2, room_rate_cents=10_000 + n
    )


def test_a_send_to_a_topic_that_does_not_exist_fails_loudly(kafka, registry):
    missing = f"test.missing.{uuid.uuid4().hex[:10]}"  # auto-create is off: the broker refuses it
    config = {
        **checkout_producer_config(kafka, delivery_timeout=5.0, principal=kafka_auth.ADMIN),
        "topic.metadata.propagation.max.ms": 1000,
    }
    producer = CheckoutProducer(
        Producer(config), registry, missing, schema=schemas.latest(topics.CHECKED_OUT), delivery_timeout=5.0
    )
    rec = event()
    started = time.monotonic()
    with pytest.raises(DeliveryFailed) as failed:
        producer.send(rec)
    assert time.monotonic() - started < 15
    assert failed.value.failed and failed.value.failed[0][0] == rec["event_id"]
    assert "UNKNOWN_TOPIC" in failed.value.failed[0][1]


def test_an_unreachable_broker_fails_loudly_after_the_delivery_timeout(kafka, registry):
    # A real refusal: nothing listens on 127.0.0.1:9. The registry is real, so the event is serialized as usual.
    producer = CheckoutProducer(
        Producer(checkout_producer_config("127.0.0.1:9", delivery_timeout=3.0)),
        registry,
        "stay.checked_out",
        schema=schemas.latest(topics.CHECKED_OUT),
        delivery_timeout=3.0,
    )
    rec = event()
    started = time.monotonic()
    with pytest.raises(DeliveryFailed) as failed:
        producer.send(rec)
    elapsed = time.monotonic() - started
    assert 2.5 <= elapsed < 15, f"failed after {elapsed:.1f} s; the delivery timeout is 3 s"
    assert failed.value.failed == [(rec["event_id"], "_MSG_TIMED_OUT")] or failed.value.undelivered == [rec["event_id"]]


def faulted_batch(registry, topic: str, *, idempotent: bool) -> tuple[int, list]:
    """Send 120 events through the proxy while it cuts every connection as the broker starts to reply, for 4 s. The
    broker writes each batch it receives; the producer loses the acknowledgement, reconnects and sends the batch
    again. Returns (ProduceRequests whose acknowledgement the proxy cut, the events sent).

    Evidence of resends: a ProduceRequest reached the broker and its acknowledgement was cut, yet flush() saw every
    event delivered, so those batches were sent again. librdkafka's own counters (txretries, req_timeouts) stay at 0
    for a request lost to a disconnect, so they can't be the proof (verification log, M2 PR-B2b)."""
    config = {
        **checkout_producer_config("127.0.0.1:19092", delivery_timeout=60.0, principal=kafka_auth.ADMIN),
        "request.timeout.ms": 1500,
    }
    if not idempotent:  # the control: the same settings an unsafe producer would have
        config.update({"enable.idempotence": False, "enable.gapless.guarantee": False})
    records = [event(m, i * 100 + n) for n in range(1, 21) for i, m in enumerate(MEMBERS, start=1)]
    with KafkaReplyCutter() as proxy:
        producer = CheckoutProducer(
            Producer(config), registry, topic, schema=schemas.latest(topics.CHECKED_OUT), delivery_timeout=60.0
        )
        producer.send(event("GR-00099", 9999))  # metadata and the schema ID are cached first
        proxy.cut_replies.set()
        for rec in records:
            producer.send(rec, flush=False)
        producer.producer.poll(4.0)  # requests reach the broker, the replies are cut, the batches are resent
        proxy.cut_replies.clear()
        producer.flush()  # raises if anything wasn't delivered
        assert proxy.forwarded_bytes > 0 and proxy.cuts > 0, "the proxy cut nothing"
        acks_cut = proxy.produce_acks_cut
    return acks_cut, records


def read_back(kafka: str, topic: str, expected: int) -> list:
    return sorted(read_raw(kafka, topic, at_least=expected, timeout=60), key=lambda m: (m.partition(), m.offset()))


def event_ids(messages: list) -> collections.Counter:
    return collections.Counter(dict(m.headers())["event_id"].decode() for m in messages)


MEMBERS = [f"GR-{m:05d}" for m in range(1, 7)]


def test_producer_retries_add_no_duplicates_and_keep_per_member_order(kafka, registry, scratch):
    """ADR-0017: idempotence must drop the batches the producer sent twice. The test fails if no ProduceRequest lost its
    acknowledgement (rule 7: a run that exercised nothing must not pass)."""
    retried, records = faulted_batch(registry, scratch["input"], idempotent=True)
    assert retried > 0, "no ProduceRequest lost its acknowledgement, so this run tested nothing"
    received = read_back(kafka, scratch["input"], len(records) + 1)
    ids = event_ids(received)
    assert set(ids.values()) == {1}, f"duplicates: {[k for k, v in ids.items() if v > 1]}"
    assert len(ids) == len(records) + 1  # nothing lost
    order: dict[str, list[str]] = collections.defaultdict(list)
    for message in received:
        order[message.key().decode()].append(dict(message.headers())["event_id"].decode())
    for member in MEMBERS:
        assert order[member] == [r["event_id"] for r in records if r["member_number"] == member]
    print(f"evidence: idempotent: {retried} ProduceRequest ack(s) cut; 0 duplicates; nothing lost; order kept")


def test_without_idempotence_the_same_fault_does_duplicate(kafka, registry, scratch):
    """The control for the test above: it shows the fault really makes the broker write a batch twice, so "0
    duplicates" there is idempotence at work and not a fault that never happened."""
    retried, records = faulted_batch(registry, scratch["output"], idempotent=False)
    assert retried > 0, "no ProduceRequest lost its acknowledgement, so this run tested nothing"
    ids = event_ids(read_back(kafka, scratch["output"], len(records) + 1))
    duplicates = sum(count - 1 for count in ids.values())
    assert duplicates > 0
    print(f"evidence: not idempotent: {retried} ProduceRequest ack(s) cut; {duplicates} duplicate message(s)")
