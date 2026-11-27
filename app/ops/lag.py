"""Consumer lag for a group: how many messages it has not yet committed, per partition (RFC-0001 test 14, OBS-03).

`compute` is pure. `read` asks Kafka through a consumer that never subscribes, so it joins no group, takes no
partition and commits nothing: it only reads the group's committed offsets and each partition's watermarks.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

Partition = tuple[str, int]


@dataclass(frozen=True)
class PartitionLag:
    topic: str
    partition: int
    committed: int | None  # None: the group has committed nothing on this partition yet
    low: int
    high: int

    @property
    def lag(self) -> int:
        """Messages between the group's position and the end. With nothing committed, the whole partition waits."""
        start = self.low if self.committed is None else max(self.committed, self.low)
        return max(self.high - start, 0)


def compute(
    committed: Mapping[Partition, int | None], watermarks: Mapping[Partition, tuple[int, int]]
) -> list[PartitionLag]:
    """One row per partition in `watermarks` (low, high). A partition missing from `committed` has no commit."""
    for partition, (low, high) in watermarks.items():
        if low < 0 or high < low:
            raise ValueError(f"impossible watermarks for {partition}: low {low}, high {high}")
    return [
        PartitionLag(topic, partition, committed.get((topic, partition)), low, high)
        for (topic, partition), (low, high) in sorted(watermarks.items())
    ]


def total(rows: list[PartitionLag]) -> int:
    return sum(row.lag for row in rows)


def read(consumer: Any, topic: str, timeout: float = 10.0) -> list[PartitionLag]:
    """Lag of the consumer's own `group.id` on `topic`. `consumer` is a confluent-kafka Consumer that was never
    subscribed or assigned; it is used for `list_topics`, `committed` and `get_watermark_offsets` only."""
    from confluent_kafka import TopicPartition

    metadata = consumer.list_topics(topic, timeout=timeout).topics.get(topic)
    if metadata is None or metadata.error is not None or not metadata.partitions:
        raise LookupError(f"topic {topic!r} is not readable")
    partitions = [TopicPartition(topic, number) for number in sorted(metadata.partitions)]
    committed = {
        (tp.topic, tp.partition): (tp.offset if tp.offset >= 0 else None)  # negative: no committed offset
        for tp in consumer.committed(partitions, timeout=timeout)
    }
    watermarks = {
        (tp.topic, tp.partition): consumer.get_watermark_offsets(tp, timeout=timeout, cached=False) for tp in partitions
    }
    return compute(committed, watermarks)
