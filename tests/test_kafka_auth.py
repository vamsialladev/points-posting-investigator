"""Kafka identities and the access list, as data (ADR-0021). Offline: the broker enforcing them is tested on the
real stack (tests/test_kafka_acls_real.py)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from app import preflight
from app.pipeline import kafka_auth as auth
from app.pipeline import topics

PIPELINE_TOPICS = (topics.CHECKED_OUT, topics.DLQ, topics.POINTS_POSTED)
ROOT = Path(__file__).resolve().parent.parent
SERVICES = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))["services"]


def test_preflight_the_template_and_the_generator_know_the_same_seven_names():
    assert preflight._KAFKA_PASSWORDS == auth.PASSWORD_VARIABLES
    template = (ROOT / ".env.example").read_text(encoding="utf-8")
    generator = (ROOT / "scripts" / "new_env.ps1").read_text(encoding="utf-8")
    for name in auth.PASSWORD_VARIABLES:
        assert f"\n{name}=\n" in template, f"{name} is in the template, empty"
        assert f'"{name}"' in generator, f"scripts/new_env.ps1 generates {name}"
        assert name in preflight._CORE, f"{name} is required by the core profile"


def test_a_kafka_password_that_would_break_the_brokers_login_list_is_invalid():
    check = preflight.VARS["KAFKA_ADMIN_PASSWORD"].check
    assert check("Abc-def_123456")
    for bad in ('has"quote-123456', "has space 123456", "back\\slash-123456", "short", "semi;colon-123456"):
        assert not check(bad), bad


def test_the_brokers_login_list_in_compose_names_every_principal_with_its_own_setting():
    line = SERVICES["kafka"]["environment"]["KAFKA_LISTENER_NAME_INTERNAL_PLAIN_SASL_JAAS_CONFIG"]
    # The same text as kafka_auth.jaas_users, with each password replaced by its ${NAME} (and its :? message).
    rendered = re.sub(r"\$\{(\w+)(?::\?[^}]*)?\}", lambda m: f"<{m.group(1)}>", line)
    expected = auth.jaas_users({name: f"<{name}>" for name in auth.PASSWORD_VARIABLES})
    assert " ".join(rendered.split()) == expected
    environment = SERVICES["kafka"]["environment"]
    for listener in ("INTERNAL", "EXTERNAL", "FAULTS"):
        assert environment[f"KAFKA_LISTENER_NAME_{listener}_PLAIN_SASL_JAAS_CONFIG"] == line
    security = dict(pair.split(":") for pair in environment["KAFKA_LISTENER_SECURITY_PROTOCOL_MAP"].split(","))
    assert security == {
        "INTERNAL": "SASL_PLAINTEXT",
        "EXTERNAL": "SASL_PLAINTEXT",
        "FAULTS": "SASL_PLAINTEXT",
        "CONTROLLER": "PLAINTEXT",  # not published; see ADR-0021
    }
    assert environment["KAFKA_AUTHORIZER_CLASS_NAME"] == "org.apache.kafka.metadata.authorizer.StandardAuthorizer"
    assert environment["KAFKA_SUPER_USERS"] == "User:admin;User:ANONYMOUS"
    assert "KAFKA_ALLOW_EVERYONE_IF_NO_ACL_FOUND" not in environment, "no ACL means refused"


def test_each_service_is_given_only_its_own_kafka_login():
    given = {
        service: sorted(name for name in definition.get("environment", {}) if name in auth.PASSWORD_VARIABLES)
        for service, definition in SERVICES.items()
    }
    assert given == {
        "db": [],
        "kafka": [],  # the broker holds every login inside its login list, not as separate settings
        "schema-registry": [],  # as KARAPACE_SASL_PLAIN_PASSWORD, checked below
        "db-init": [],
        "kafka-init": ["KAFKA_ADMIN_PASSWORD"],
        "ledger": [],
        "posting": ["KAFKA_POSTING_PASSWORD"],
        "retry-worker": ["KAFKA_POSTING_PASSWORD"],
        "relay": ["KAFKA_RELAY_PASSWORD"],
    }
    registry = SERVICES["schema-registry"]["environment"]
    assert registry["KARAPACE_SASL_PLAIN_USERNAME"] == auth.REGISTRY
    assert "${KAFKA_REGISTRY_PASSWORD" in registry["KARAPACE_SASL_PLAIN_PASSWORD"]
    assert (registry["KARAPACE_SECURITY_PROTOCOL"], registry["KARAPACE_SASL_MECHANISM"]) == ("SASL_PLAINTEXT", "PLAIN")
    assert registry["KARAPACE_TOPIC_NAME"] == auth.REGISTRY_TOPIC
    assert registry["KARAPACE_GROUP_ID"].startswith(auth.REGISTRY_GROUP_PREFIX)
    for service in ("posting", "retry-worker", "relay", "ledger"):
        environment = SERVICES[service].get("environment", {})
        assert "KAFKA_INVESTIGATOR_PASSWORD" not in environment and "KAFKA_REPLAYER_PASSWORD" not in environment


def test_without_a_password_the_settings_are_plain_and_localhost_is_ipv4():
    assert auth.client_config(auth.POSTING, "localhost:9092", env={}) == {"bootstrap.servers": "127.0.0.1:9092"}


def test_with_its_password_a_client_logs_in_as_its_own_principal_only():
    env = {"KAFKA_POSTING_PASSWORD": "posting-pw", "KAFKA_ADMIN_PASSWORD": "admin-pw"}
    config = auth.client_config(auth.POSTING, "127.0.0.1:9092", env=env)
    assert config == {
        "bootstrap.servers": "127.0.0.1:9092",
        "security.protocol": "SASL_PLAINTEXT",
        "sasl.mechanism": "PLAIN",
        "sasl.username": "posting",
        "sasl.password": "posting-pw",
    }
    assert "sasl.username" not in auth.client_config(auth.RELAY, "127.0.0.1:9092", env=env), "no borrowed password"


def test_an_unknown_principal_is_refused():
    for call in (lambda: auth.client_config("root", "x:1", env={}), lambda: auth.password_variable("investigator2")):
        with pytest.raises(ValueError):
            call()
    assert auth.PASSWORD_VARIABLES[0] == "KAFKA_ADMIN_PASSWORD" and len(auth.PASSWORD_VARIABLES) == 7


def test_the_investigator_can_only_describe_and_read():
    """The guarantee, as data: no entry lets the investigator write, create, delete or alter anything."""
    mine = [acl for acl in auth.ACLS if acl.principal == auth.INVESTIGATOR]
    assert mine, "the investigator has an access list"
    assert {acl.operation for acl in mine} == {"read", "describe"}
    assert not {acl.operation for acl in mine} & auth.WRITE_LIKE
    for topic in PIPELINE_TOPICS:
        assert auth.operations(auth.INVESTIGATOR, "topic", topic) == {"read", "describe"}
    assert auth.operations(auth.INVESTIGATOR, "group", auth.POSTING_GROUP) == {"describe"}, "it can't commit offsets"
    assert auth.operations(auth.INVESTIGATOR, "cluster", auth.CLUSTER) == set()
    assert auth.operations(auth.INVESTIGATOR, "topic", auth.REGISTRY_TOPIC) == set()


def test_each_writer_can_write_exactly_one_topic():
    writable = {
        principal: {
            t
            for t in (*PIPELINE_TOPICS, auth.REGISTRY_TOPIC)
            if auth.operations(principal, "topic", t) & {"write", "all"}
        }
        for principal in auth.PRINCIPALS
    }
    assert writable == {
        auth.ADMIN: set(),  # a super user: it has no entries, the broker lets it do everything
        auth.PRODUCER: {topics.CHECKED_OUT},
        auth.POSTING: {topics.DLQ},
        auth.RELAY: {topics.POINTS_POSTED},
        auth.REGISTRY: {auth.REGISTRY_TOPIC},
        auth.INVESTIGATOR: set(),
        auth.REPLAYER: {topics.CHECKED_OUT},
    }


def test_only_the_posting_service_can_commit_in_the_posting_group_and_the_replayer_reads_nothing():
    readers = {p for p in auth.PRINCIPALS if "read" in auth.operations(p, "group", auth.POSTING_GROUP)}
    assert readers == {auth.POSTING}
    assert all("read" not in auth.operations(auth.REPLAYER, "topic", t) for t in PIPELINE_TOPICS)
    assert all("read" not in auth.operations(auth.PRODUCER, "topic", t) for t in PIPELINE_TOPICS)


def test_the_list_names_only_known_principals_resources_and_operations_and_never_the_admin():
    known = {"read", "write", "describe", "create", "all", "idempotent_write", "describe_configs"}
    assert len(set(auth.ACLS)) == len(auth.ACLS), "no entry twice"
    for acl in auth.ACLS:
        assert acl.principal in auth.PRINCIPALS and acl.principal != auth.ADMIN
        assert acl.resource in ("topic", "group", "cluster") and acl.operation in known
        assert (acl.resource == "cluster") == (acl.name == auth.CLUSTER)
    assert auth.operations(auth.REGISTRY, "group", "karapace-local") == {"all"}, "a prefixed entry matches by prefix"
    assert auth.operations(auth.REGISTRY, "group", auth.POSTING_GROUP) == set()


def test_the_jaas_line_lists_every_principal_once():
    passwords = {variable: f"pw-{n}" for n, variable in enumerate(auth.PASSWORD_VARIABLES)}
    line = auth.jaas_users(passwords)
    assert line.startswith("org.apache.kafka.common.security.plain.PlainLoginModule required ") and line.endswith(";")
    assert 'username="admin" password="pw-0"' in line
    for n, principal in enumerate(auth.PRINCIPALS):
        assert line.count(f'user_{principal}="pw-{n}"') == 1
