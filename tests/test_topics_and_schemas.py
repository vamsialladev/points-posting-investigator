"""Topic layout and the committed Avro schemas, offline (RFC-0001 D4, D7, D8)."""

import json

import fastavro
import pytest

from app.pipeline import schemas, topics


def test_the_topics_match_the_rfc():
    names = [spec.name for spec in topics.TOPICS]
    assert names == [
        "stay.checked_out",
        "stay.checked_out.retry.1",
        "stay.checked_out.retry.2",
        "stay.checked_out.retry.3",
        "stay.checked_out.dlq",
        "points.posted",
    ]
    assert {spec.partitions for spec in topics.TOPICS} == {3}
    assert {spec.replication for spec in topics.TOPICS} == {1}


def test_the_dlq_keeps_messages_longest():
    retention = {spec.name: int(spec.config["retention.ms"]) for spec in topics.TOPICS}
    assert retention[topics.DLQ] == max(retention.values()) > retention[topics.CHECKED_OUT]


@pytest.mark.parametrize("attempt", [0, 4])
def test_there_are_exactly_three_retry_topics(attempt):
    with pytest.raises(ValueError):
        topics.retry_topic(attempt)


def test_new_topic_carries_the_spec():
    new = topics.TopicSpec("x", partitions=2, config={"retention.ms": "1"}).new_topic()
    assert (new.topic, new.num_partitions, new.replication_factor) == ("x", 2, 1)


@pytest.mark.parametrize("topic", [topics.CHECKED_OUT, topics.POINTS_POSTED])
def test_every_value_topic_has_a_valid_committed_avro_schema(topic):
    found = schemas.versions(topic)
    assert found and found[0][0] == 1
    parsed = fastavro.parse_schema(json.loads(schemas.latest(topic)))
    assert parsed["type"] == "record"
    assert "synthetic data" in json.loads(schemas.latest(topic))["doc"]


def test_money_is_in_cents_and_only_the_room_rate_earns():
    fields = {f["name"]: f for f in json.loads(schemas.latest(topics.CHECKED_OUT))["fields"]}
    assert {fields[name]["type"] for name in ("room_rate_cents", "taxes_cents", "fees_cents")} == {"long"}
    assert fields["revision"]["default"] == 1  # D10: a correction is a higher revision
    assert "10 per US dollar" in json.loads(schemas.latest(topics.CHECKED_OUT))["doc"]


def test_subjects_and_compatibility():
    assert schemas.subject("points.posted") == "points.posted-value"
    assert schemas.COMPATIBILITY == "BACKWARD_TRANSITIVE"


def test_a_missing_schema_fails_loudly():
    with pytest.raises(FileNotFoundError):
        schemas.latest("no.such.topic")
