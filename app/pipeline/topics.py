"""The pipeline's Kafka topics, created explicitly (auto-creation is off in the broker) (RFC-0001 D7, D8).

    python -m app.pipeline.topics     # uses KAFKA_BOOTSTRAP_SERVERS

Three partitions each, keyed by `member_number`, so one member's events stay in order on one partition.
Replication factor 1, because the local stack has one broker: dev-only, documented in docs/scaling-and-limits.md.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

from confluent_kafka.admin import AdminClient
from confluent_kafka.cimpl import NewTopic

CHECKED_OUT = "stay.checked_out"
POINTS_POSTED = "points.posted"
RETRY_DELAYS_SECONDS = (5, 30, 120)  # D8: retry.1, retry.2, retry.3; tests inject shorter ones
DAY_MS = 24 * 60 * 60 * 1000


def retry_topic(attempt: int) -> str:
    if not 1 <= attempt <= len(RETRY_DELAYS_SECONDS):
        raise ValueError(f"retry attempt must be 1..{len(RETRY_DELAYS_SECONDS)}")
    return f"{CHECKED_OUT}.retry.{attempt}"


DLQ = f"{CHECKED_OUT}.dlq"


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
    *(TopicSpec(retry_topic(n), config={"retention.ms": str(7 * DAY_MS)}) for n in (1, 2, 3)),
    # The DLQ keeps messages longer: an operator replays from it (M7, with approval).
    TopicSpec(DLQ, config={"retention.ms": str(30 * DAY_MS)}),
    TopicSpec(POINTS_POSTED, config={"retention.ms": str(7 * DAY_MS)}),
)


def ensure_topics(bootstrap: str, specs: tuple[TopicSpec, ...] = TOPICS, timeout: float = 30.0) -> list[str]:
    """Create the topics that don't exist yet. Returns the names it created."""
    admin = AdminClient({"bootstrap.servers": bootstrap})
    existing = set(admin.list_topics(timeout=timeout).topics)
    missing = [spec for spec in specs if spec.name not in existing]
    if not missing:
        return []
    futures = admin.create_topics([spec.new_topic() for spec in missing], operation_timeout=timeout)
    for future in futures.values():
        future.result(timeout=timeout)  # raises on failure, so the init container exits non-zero
    return [spec.name for spec in missing]


def main() -> int:
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    created = ensure_topics(bootstrap)
    print(f"topics: {len(TOPICS)} expected; created {created or 'none (all present)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
