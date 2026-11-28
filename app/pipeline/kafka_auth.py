"""Who each process is to Kafka, and what each identity may do (RFC-0002 Phase 2, ADR-0021). Pure: no I/O here.

- `client_config(principal, bootstrap)` is the one place a Kafka client's connection settings are built. With that
  principal's password in the environment the client logs in with SASL/PLAIN; without it the settings are plain
  (unit tests, and a stack that predates SASL).
- `ACLS` is the whole access list, as data. `python -m app.pipeline.topics` applies it after creating the topics.
  A principal gets exactly these rights and nothing else: the broker refuses everything not listed.

The investigator can describe and read. It has no Write on any topic, so it can't produce, replay or post, whatever
its code or its prompt says. Local stack only: SASL here runs without TLS, on loopback.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.pipeline import topics

ADMIN = "admin"  # the broker itself, topic and ACL creation, scenarios and tests: a super user
PRODUCER = "producer"  # the simulated property system (producer, load generator)
POSTING = "posting"  # the posting service and the retry worker
RELAY = "relay"  # the outbox relay
REGISTRY = "registry"  # the schema registry (Karapace)
INVESTIGATOR = "investigator"  # read-only
REPLAYER = "replayer"  # human-approved replay (RFC-0002 Phase 5)
PRINCIPALS = (ADMIN, PRODUCER, POSTING, RELAY, REGISTRY, INVESTIGATOR, REPLAYER)

POSTING_GROUP = "posting-service"
REGISTRY_TOPIC = "_schemas"
REGISTRY_GROUP_PREFIX = "karapace"


def password_variable(principal: str) -> str:
    if principal not in PRINCIPALS:
        raise ValueError(f"unknown Kafka principal {principal!r}")
    return f"KAFKA_{principal.upper()}_PASSWORD"


PASSWORD_VARIABLES = tuple(password_variable(principal) for principal in PRINCIPALS)


def client_config(principal: str, bootstrap: str, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Connection settings for a Kafka client acting as `principal`. Never logged: it can hold a password."""
    variable = password_variable(principal)
    password = (os.environ if env is None else env).get(variable, "")
    config: dict[str, Any] = {"bootstrap.servers": bootstrap.replace("localhost", "127.0.0.1")}
    if password:
        config.update(
            {
                "security.protocol": "SASL_PLAINTEXT",
                "sasl.mechanism": "PLAIN",
                "sasl.username": principal,
                "sasl.password": password,
            }
        )
    return config


@dataclass(frozen=True)
class Acl:
    principal: str
    resource: str  # topic | group | cluster
    name: str
    operation: str  # read | write | describe | create | all | idempotent_write | describe_configs
    prefixed: bool = False  # the name is a prefix, not an exact name


def _topic(principal: str, name: str, *operations: str, prefixed: bool = False) -> tuple[Acl, ...]:
    return tuple(Acl(principal, "topic", name, operation, prefixed) for operation in operations)


CLUSTER = "kafka-cluster"  # the cluster resource's fixed name

ACLS: tuple[Acl, ...] = (
    # The simulated property system only writes checkout events.
    *_topic(PRODUCER, topics.CHECKED_OUT, "write", "describe"),
    Acl(PRODUCER, "cluster", CLUSTER, "idempotent_write"),
    # The posting service and retry worker read checkouts in their group and write dead letters. They can't write
    # a checkout event or a points.posted record.
    *_topic(POSTING, topics.CHECKED_OUT, "read", "describe"),
    Acl(POSTING, "group", POSTING_GROUP, "read"),
    Acl(POSTING, "group", POSTING_GROUP, "describe"),
    *_topic(POSTING, topics.DLQ, "write", "describe"),
    Acl(POSTING, "cluster", CLUSTER, "idempotent_write"),
    # The relay only writes points.posted.
    *_topic(RELAY, topics.POINTS_POSTED, "write", "describe"),
    Acl(RELAY, "cluster", CLUSTER, "idempotent_write"),
    # The schema registry keeps its schemas in its own topic, with its own groups.
    *_topic(REGISTRY, REGISTRY_TOPIC, "all"),
    Acl(REGISTRY, "group", REGISTRY_GROUP_PREFIX, "all", prefixed=True),
    Acl(REGISTRY, "cluster", CLUSTER, "describe"),
    Acl(REGISTRY, "cluster", CLUSTER, "describe_configs"),
    # The investigator reads the pipeline's three topics and the posting group's offsets. Nothing else.
    *_topic(INVESTIGATOR, topics.CHECKED_OUT, "read", "describe"),
    *_topic(INVESTIGATOR, topics.DLQ, "read", "describe"),
    *_topic(INVESTIGATOR, topics.POINTS_POSTED, "read", "describe"),
    Acl(INVESTIGATOR, "group", POSTING_GROUP, "describe"),
    # The replayer may put an approved event back on the checkout topic. It can't read anything.
    *_topic(REPLAYER, topics.CHECKED_OUT, "write", "describe"),
    Acl(REPLAYER, "cluster", CLUSTER, "idempotent_write"),
)
WRITE_LIKE = frozenset({"write", "create", "all", "idempotent_write", "delete", "alter", "alter_configs"})


def operations(principal: str, resource: str, name: str) -> set[str]:
    """What `principal` may do on one resource, by this table (exact and prefixed entries)."""
    return {
        acl.operation
        for acl in ACLS
        if acl.principal == principal
        and acl.resource == resource
        and (name.startswith(acl.name) if acl.prefixed else name == acl.name)
    }


def jaas_users(passwords: Mapping[str, str]) -> str:
    """The broker's JAAS line: every principal with its password. Used only to check the compose file's own line."""
    users = " ".join(f'user_{principal}="{passwords[password_variable(principal)]}"' for principal in PRINCIPALS)
    admin = passwords[password_variable(ADMIN)]
    return (
        "org.apache.kafka.common.security.plain.PlainLoginModule required "
        f'username="{ADMIN}" password="{admin}" {users};'
    )
