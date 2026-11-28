"""Take one snapshot of the evidence: every stored read plus the three topics and the lag, since a given time.

    python -m app.evidence.snapshot --minutes 15 [--out file.json]

The command reads the local stack as the read-only roles and prints (or writes) the snapshot as JSON. It changes
nothing. A read that hits its limit is listed under `truncated`, so "nothing found" is never confused with
"not everything was read" (standing rule 7).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.evidence.model import Evidence, Snapshot
from app.evidence.store import QUERIES, EvidenceStore, engines_from_env
from app.evidence.topics import TopicReader

STORED_READS = tuple(QUERIES)


def collect(
    store: EvidenceStore,
    topics_reader: TopicReader | None,
    since: datetime,
    *,
    now: datetime | None = None,
    limit: int = 200,
    topic_limit: int = 500,
) -> Snapshot:
    """Everything since `since`. Topic messages older than that are dropped after reading (Kafka reads by offset)."""
    from app.pipeline import topics as names

    taken = now or datetime.now(UTC)
    items: list[Evidence] = []
    truncated: list[str] = []
    for name in STORED_READS:
        found, more = store.read(name, since, limit)
        items.extend(found)
        if more:
            truncated.append(name)
    if topics_reader is not None:
        for topic, dead in ((names.CHECKED_OUT, False), (names.DLQ, True), (names.POINTS_POSTED, False)):
            found, more = topics_reader.messages(topic, dead_letter=dead, limit=topic_limit)
            recent = [item for item in found if item.at is None or item.at >= since.isoformat()]
            items.extend(recent)
            if more and len(recent) == len(found):  # older messages were left out and nothing bounded them by time
                truncated.append(topic)
        if topics_reader.group:
            items.extend(topics_reader.lag(names.CHECKED_OUT))
    unique = {item.id: item for item in items}  # the two log reads can't overlap, but an id is cited once
    return Snapshot(taken.isoformat(), since.isoformat(), tuple(unique.values()), tuple(truncated))


def reader_from_env(env: Mapping[str, str]) -> TopicReader:
    """A topic reader that logs in as `investigator` and decodes checkout events through the schema registry."""
    from confluent_kafka.schema_registry import SchemaRegistryClient
    from confluent_kafka.schema_registry.avro import AvroDeserializer
    from confluent_kafka.serialization import MessageField, SerializationContext

    from app.pipeline import kafka_auth

    registry_url = env.get("SCHEMA_REGISTRY_URL", "http://127.0.0.1:8081").replace("://localhost", "://127.0.0.1")
    deserializer = AvroDeserializer(SchemaRegistryClient({"url": registry_url, "timeout": 10}))

    def decode(value: bytes, topic: str) -> dict[str, Any]:
        record = deserializer(value, SerializationContext(topic, MessageField.VALUE))
        if not isinstance(record, dict):
            raise ValueError("not a record")
        return record

    base = kafka_auth.client_config(kafka_auth.INVESTIGATOR, env.get("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092"), env)
    return TopicReader(base, decode, group=kafka_auth.POSTING_GROUP)


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(description="One read-only snapshot of the stored evidence, as JSON")
    parser.add_argument("--minutes", type=float, default=15.0, help="how far back to read")
    parser.add_argument("--out", type=Path, help="write here instead of printing")
    args = parser.parse_args(argv)
    if not 0 < args.minutes <= 24 * 60:
        raise SystemExit("--minutes must be above 0 and at most 1440")
    load_dotenv(override=False)
    try:
        store = EvidenceStore(engines_from_env(os.environ))
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    snapshot = collect(store, reader_from_env(os.environ), datetime.now(UTC) - timedelta(minutes=args.minutes))
    text = json.dumps(snapshot.to_json(), indent=2, default=str)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
        print(
            f"{len(snapshot.items)} items -> {args.out}"
            + (f"; truncated: {', '.join(snapshot.truncated)}" if snapshot.truncated else "")
        )
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
