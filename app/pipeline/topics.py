"""The pipeline's Kafka topics, created explicitly (auto-creation is off in the broker) (RFC-0001 D7).

    python -m app.pipeline.topics     # uses KAFKA_BOOTSTRAP_SERVERS

Three partitions each, keyed by `member_number`, so one member's events stay in order on one partition.
Replication factor 1, because the local stack has one broker: dev-only, documented in docs/scaling-and-limits.md.

There are no retry topics (ADR-0016, replacing RFC-0001 D8). A failed event is parked in Postgres behind the member's
earlier parked events, which keeps per-member order; a retry topic would let event 2 overtake event 1. A stack created
before B2b still has the three `.retry.N` topics, unused; recreating the Kafka container drops them.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any

from confluent_kafka import admin as kafka_admin
from confluent_kafka.admin import AdminClient
from confluent_kafka.cimpl import NewTopic

# The package's public names for ACLs; its type stubs don't list them as exported, so mypy needs them this way.
AclBinding: Any = kafka_admin.AclBinding  # type: ignore[attr-defined]
AclOperation: Any = kafka_admin.AclOperation  # type: ignore[attr-defined]
AclPermissionType: Any = kafka_admin.AclPermissionType  # type: ignore[attr-defined]
ResourcePatternType: Any = kafka_admin.ResourcePatternType  # type: ignore[attr-defined]
ResourceType: Any = kafka_admin.ResourceType  # type: ignore[attr-defined]

CHECKED_OUT = "stay.checked_out"
POINTS_POSTED = "points.posted"
DLQ = f"{CHECKED_OUT}.dlq"
DAY_MS = 24 * 60 * 60 * 1000


@dataclass(frozen=True)
class TopicSpec:
    name: str
    partitions: int = 3
    replication: int = 1
    config: dict[str, str] = field(default_factory=dict)

    def new_topic(self) -> NewTopic:
        return NewTopic(
            self.name, num_partitions=self.partitions, replication_factor=self.replication, config=self.config
        )


TOPICS: tuple[TopicSpec, ...] = (
    TopicSpec(CHECKED_OUT, config={"retention.ms": str(7 * DAY_MS)}),
    # The DLQ keeps messages longer: an operator replays from it (M7, with approval).
    TopicSpec(DLQ, config={"retention.ms": str(30 * DAY_MS)}),
    TopicSpec(POINTS_POSTED, config={"retention.ms": str(7 * DAY_MS)}),
)


def ensure_topics(bootstrap: str, specs: tuple[TopicSpec, ...] = TOPICS, timeout: float = 30.0) -> list[str]:
    """Create the topics that don't exist yet. Returns the names it created."""
    from app.pipeline import kafka_auth  # it imports this module's topic names

    admin = AdminClient(kafka_auth.client_config(kafka_auth.ADMIN, bootstrap))
    existing = set(admin.list_topics(timeout=timeout).topics)
    missing = [spec for spec in specs if spec.name not in existing]
    if not missing:
        return []
    futures = admin.create_topics([spec.new_topic() for spec in missing], operation_timeout=timeout)
    for future in futures.values():
        future.result(timeout=timeout)  # raises on failure, so the init container exits non-zero
    return [spec.name for spec in missing]


def acl_bindings(acls: tuple[Any, ...]) -> list[Any]:
    """The access list (`kafka_auth.ACLS`) as the broker's bindings: allow, from any host."""
    resources = {"topic": ResourceType.TOPIC, "group": ResourceType.GROUP, "cluster": ResourceType.BROKER}
    return [
        AclBinding(
            resources[acl.resource],
            acl.name,
            ResourcePatternType.PREFIXED if acl.prefixed else ResourcePatternType.LITERAL,
            f"User:{acl.principal}",
            "*",
            AclOperation[acl.operation.upper()],
            AclPermissionType.ALLOW,
        )
        for acl in acls
    ]


def ensure_acls(bootstrap: str, timeout: float = 30.0) -> int:
    """Apply the whole access list. Creating a binding that exists is not an error, so this can run at every start.
    Returns how many bindings were sent. It only ever adds: a binding removed from the list must be deleted by hand."""
    from app.pipeline import kafka_auth

    admin = AdminClient(kafka_auth.client_config(kafka_auth.ADMIN, bootstrap))
    bindings = acl_bindings(kafka_auth.ACLS)
    for future in admin.create_acls(bindings, request_timeout=timeout).values():
        future.result(timeout=timeout)  # raises on failure, so the init container exits non-zero
    return len(bindings)


def main() -> int:
    from app.pipeline import kafka_auth

    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    created = ensure_topics(bootstrap)
    print(f"topics: {len(TOPICS)} expected; created {created or 'none (all present)'}")
    if os.environ.get(kafka_auth.password_variable(kafka_auth.ADMIN)):
        print(f"access list: {ensure_acls(bootstrap)} binding(s) applied")
    else:
        print("access list: not applied (no KAFKA_ADMIN_PASSWORD: the broker runs without authentication)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
