"""The broker enforces the access list (ADR-0021), on the real stack. Each check logs in as a real principal.

The point of these tests: the investigator's read-only guarantee doesn't rest on its code. Its Kafka login can't
write, commit, create or grant, whatever the process holding it tries.

Needs TEST_KAFKA_BOOTSTRAP_SERVERS and the stack's KAFKA_*_PASSWORD values in the environment
(scripts\\test_integration.ps1 passes them on without printing them). Nothing here writes to a pipeline topic: every
write attempted is one the broker must refuse.
"""

from __future__ import annotations

import os
import uuid

import pytest
from confluent_kafka import Consumer, KafkaError, KafkaException, Producer, TopicPartition
from confluent_kafka.admin import AdminClient
from confluent_kafka.cimpl import NewTopic

from app.ops import lag
from app.pipeline import kafka_auth as auth
from app.pipeline import topics

pytestmark = pytest.mark.kafka
PIPELINE_TOPICS = (topics.CHECKED_OUT, topics.DLQ, topics.POINTS_POSTED)


@pytest.fixture(scope="module")
def logins(kafka) -> str:
    missing = [name for name in auth.PASSWORD_VARIABLES if not os.environ.get(name)]
    if missing:
        pytest.skip(f"{', '.join(missing)} not set: the stack's Kafka logins are needed to test the access list")
    return kafka


def config(principal: str, bootstrap: str, **more: object) -> dict[str, object]:
    settings = auth.client_config(principal, bootstrap)
    assert settings["sasl.username"] == principal, "the client really logs in as this principal"
    return {**settings, **more}


def produce_error(principal: str, bootstrap: str, topic: str) -> KafkaError | None:
    """Try to produce one message as `principal`. Returns the delivery error, or None if the broker took it."""
    reports: list[KafkaError | None] = []
    producer = Producer(config(principal, bootstrap, **{"message.timeout.ms": 10_000}))
    producer.produce(
        topic, key=b"acl-test", value=b"must be refused", on_delivery=lambda err, _msg: reports.append(err)
    )
    producer.flush(20)
    assert len(reports) == 1, "the produce attempt got a delivery report"
    return reports[0]


@pytest.mark.parametrize("topic", PIPELINE_TOPICS)
def test_the_investigator_cannot_produce_to_any_pipeline_topic(logins, topic):
    error = produce_error(auth.INVESTIGATOR, logins, topic)
    assert error is not None, f"the broker accepted an investigator's message on {topic}"
    assert error.code() == KafkaError.TOPIC_AUTHORIZATION_FAILED, error


def test_the_investigator_can_read_the_posting_groups_lag_without_joining_it(logins):
    consumer = Consumer(
        config(auth.INVESTIGATOR, logins, **{"group.id": auth.POSTING_GROUP, "enable.auto.commit": False})
    )
    try:
        rows = lag.read(consumer, topics.CHECKED_OUT)
        assert len(rows) == 3 and all(row.lag >= 0 for row in rows)
    finally:
        consumer.close()


def test_the_investigator_can_read_messages_but_cannot_commit_an_offset(logins):
    consumer = Consumer(
        config(
            auth.INVESTIGATOR,
            logins,
            **{"group.id": auth.POSTING_GROUP, "enable.auto.commit": False, "auto.offset.reset": "earliest"},
        )
    )
    try:
        partition = TopicPartition(topics.CHECKED_OUT, 0, 0)
        consumer.assign([partition])  # assigned, not subscribed: it joins no group
        message = consumer.poll(10)
        assert message is None or message.error() is None, "reading the topic is allowed"
        with pytest.raises(KafkaException) as refused:
            consumer.commit(offsets=[partition], asynchronous=False)
        assert refused.value.args[0].code() == KafkaError.GROUP_AUTHORIZATION_FAILED
    finally:
        consumer.close()


def test_the_investigator_cannot_create_a_topic_or_change_the_access_list(logins):
    admin = AdminClient(config(auth.INVESTIGATOR, logins))
    name = f"test.acl.{uuid.uuid4().hex[:8]}"
    with pytest.raises(KafkaException) as no_topic:
        admin.create_topics([NewTopic(name, num_partitions=1, replication_factor=1)])[name].result(timeout=20)
    assert no_topic.value.args[0].code() in (
        KafkaError.TOPIC_AUTHORIZATION_FAILED,
        KafkaError.CLUSTER_AUTHORIZATION_FAILED,
    )
    grant = topics.acl_bindings((auth.Acl(auth.INVESTIGATOR, "topic", topics.CHECKED_OUT, "write"),))
    with pytest.raises(KafkaException) as no_grant:
        next(iter(admin.create_acls(grant, request_timeout=20).values())).result(timeout=20)
    assert no_grant.value.args[0].code() == KafkaError.CLUSTER_AUTHORIZATION_FAILED
    assert produce_error(auth.INVESTIGATOR, logins, topics.CHECKED_OUT) is not None, "and it still can't write"


def test_the_posting_service_cannot_write_checkouts_and_the_relay_cannot_write_dead_letters(logins):
    for principal, topic in (
        (auth.POSTING, topics.CHECKED_OUT),
        (auth.POSTING, topics.POINTS_POSTED),
        (auth.RELAY, topics.DLQ),
        (auth.RELAY, topics.CHECKED_OUT),
        (auth.PRODUCER, topics.POINTS_POSTED),
        (auth.REPLAYER, topics.POINTS_POSTED),
    ):
        error = produce_error(principal, logins, topic)
        assert error is not None and error.code() == KafkaError.TOPIC_AUTHORIZATION_FAILED, (principal, topic, error)


def test_a_wrong_password_and_a_client_with_no_login_are_both_refused(logins):
    wrong = {**config(auth.INVESTIGATOR, logins), "sasl.password": "not-the-password-" + uuid.uuid4().hex}
    plain = {"bootstrap.servers": logins}
    for settings in (wrong, plain):
        with pytest.raises(KafkaException):
            AdminClient(settings).list_topics(timeout=8)


def test_the_access_list_on_the_broker_is_the_one_in_the_code(logins):
    from confluent_kafka import admin as kafka_admin

    from app.pipeline.topics import AclBinding  # the client's own class (see topics.py)

    everything = kafka_admin.AclBindingFilter(  # type: ignore[attr-defined]
        kafka_admin.ResourceType.ANY,  # type: ignore[attr-defined]
        None,
        kafka_admin.ResourcePatternType.ANY,  # type: ignore[attr-defined]
        None,
        None,
        kafka_admin.AclOperation.ANY,  # type: ignore[attr-defined]
        kafka_admin.AclPermissionType.ANY,  # type: ignore[attr-defined]
    )
    admin = AdminClient(config(auth.ADMIN, logins))  # kept in a name: the answer is lost if the client is collected
    found = admin.describe_acls(everything, request_timeout=20).result(timeout=20)
    on_broker = {
        (b.principal, b.restype.name, b.name, b.resource_pattern_type.name, b.operation.name, b.permission_type.name)
        for b in found
    }
    in_code = {
        (b.principal, b.restype.name, b.name, b.resource_pattern_type.name, b.operation.name, b.permission_type.name)
        for b in topics.acl_bindings(auth.ACLS)
    }
    assert AclBinding is not None and on_broker == in_code, "nothing extra on the broker, nothing missing"
