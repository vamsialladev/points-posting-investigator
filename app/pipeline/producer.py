"""The checkout event producer: a simulated property-management system (synthetic data, RFC-0001 B1, ADR-0015).

    python -m app.pipeline.producer --count 5 [--seed 42]

Every event is the committed Avro `stay.checked_out` v1, keyed by `member_number` (one member's events stay in order
on one partition). Each carries these headers:
- `event_id`: its idempotency key, a UUID kept when the same event is sent again
- `schema_version`
- `correlation_id`
- a W3C `traceparent` that starts the trace the posting service and the relay continue

The producer is idempotent (`enable.idempotence`, `acks=all`): its own retries add no duplicates. A resend by the
application does, by design, and the posting service recognises it.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from confluent_kafka import Producer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroSerializer
from confluent_kafka.serialization import MessageField, SerializationContext

from app.pipeline import schemas, topics, trace
from app.pipeline.events import PROPERTIES, TENANT

SCHEMA_VERSION = "1"


def build_event(
    *,
    member_number: str,
    stay_id: str,
    check_in: date,
    nights: int,
    room_rate_cents: int,
    property: str | None = None,  # the schema's field name
    taxes_cents: int = 0,
    fees_cents: int = 0,
    revision: int = 1,
    event_id: str | None = None,
    correlation_id: str | None = None,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    """A `stay.checked_out` record. The property defaults from the stay ID prefix (BR- / ML-)."""
    prefix = stay_id.split("-", 1)[0]
    prop = property or next(name for name, p in PROPERTIES.items() if p == prefix)
    event_id = event_id or str(uuid.uuid4())
    return {
        "event_id": event_id,
        "occurred_at": occurred_at or datetime.now(UTC),
        "tenant": TENANT,
        "property": prop,
        "stay_id": stay_id,
        "member_number": member_number,
        "revision": revision,
        "check_in": check_in,
        "check_out": check_in + timedelta(days=nights),
        "nights": nights,
        "room_rate_cents": room_rate_cents,
        "taxes_cents": taxes_cents,
        "fees_cents": fees_cents,
        "currency": "USD",
        "correlation_id": correlation_id or f"corr-{event_id[:8]}",
    }


@dataclass(frozen=True)
class Sent:
    event_id: str
    traceparent: str


class CheckoutProducer:
    def __init__(
        self,
        producer: Any,
        registry: SchemaRegistryClient | None,
        topic: str = topics.CHECKED_OUT,
        schema: str = "",
        serialize: Callable[[dict[str, Any], SerializationContext], bytes] | None = None,
    ) -> None:
        """`serialize` replaces the Avro serializer (unit tests); otherwise `registry` is required."""
        self.producer = producer
        self.topic = topic
        if serialize is None:
            if registry is None:
                raise ValueError("a schema registry client is required")
            serialize = AvroSerializer(registry, schema or schemas.latest(topics.CHECKED_OUT))
        self._serialize = serialize

    def send(self, record: dict[str, Any], traceparent: str | None = None, flush: bool = True) -> Sent:
        traceparent = traceparent or trace.new_traceparent()
        headers = {
            "event_id": record["event_id"],
            "schema_version": SCHEMA_VERSION,
            "correlation_id": record["correlation_id"],
            "traceparent": traceparent,
        }
        value = self._serialize(record, SerializationContext(self.topic, MessageField.VALUE))
        self.producer.produce(
            self.topic, key=record["member_number"].encode(), value=value, headers=list(headers.items())
        )
        if flush:
            self.flush()
        return Sent(record["event_id"], traceparent)

    def flush(self, timeout: float = 30.0) -> None:
        remaining = self.producer.flush(timeout)
        if remaining:
            raise RuntimeError(f"{remaining} event(s) not delivered within {timeout} s")


def synthetic_events(count: int, seed: int) -> list[dict[str, Any]]:
    """Synthetic checkouts for the demo (the load generator with rates comes in PR-C)."""
    rng = random.Random(seed)  # noqa: S311 (synthetic data, not security)
    events = []
    for n in range(count):
        prefix = rng.choice(["BR", "ML"])
        events.append(
            build_event(
                member_number=f"GR-{rng.randint(1, 500):05d}",
                stay_id=f"{prefix}-{rng.randint(1, 9999):04d}",
                check_in=date(2026, 11, 1) + timedelta(days=n % 20),
                nights=rng.randint(1, 5),
                room_rate_cents=rng.randint(9_000, 60_000),
                taxes_cents=rng.randint(0, 6_000),
                fees_cents=rng.choice([0, 2_500, 3_000]),
            )
        )
    return events


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv(override=False)
    parser = argparse.ArgumentParser(description="Send synthetic stay.checked_out events")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    if not 1 <= args.count <= 1000:
        raise SystemExit("--count must be between 1 and 1000 (the load generator in PR-C does rates)")
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092").replace("localhost", "127.0.0.1")
    registry = SchemaRegistryClient({"url": os.environ.get("SCHEMA_REGISTRY_URL", "http://127.0.0.1:8081")})
    producer = CheckoutProducer(
        Producer({"bootstrap.servers": bootstrap, "enable.idempotence": True, "acks": "all"}), registry
    )
    for record in synthetic_events(args.count, args.seed):
        producer.send(record, flush=False)
    producer.flush()
    print(f"sent {args.count} synthetic stay.checked_out event(s) to {producer.topic}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
