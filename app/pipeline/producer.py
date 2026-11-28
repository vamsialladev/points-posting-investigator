"""The checkout event producer: a simulated property-management system (synthetic data, RFC-0001 B1, ADR-0015).

    python -m app.pipeline.producer --count 5 [--seed 42]

Every event is the committed Avro `stay.checked_out` v1, keyed by `member_number` (one member's events stay in order
on one partition). Each carries these headers:
- `event_id`: its idempotency key, a UUID kept when the same event is sent again
- `schema_version`
- `correlation_id`
- a W3C `traceparent` that starts the trace the posting service and the relay continue

Delivery (ADR-0017, after the incident of 2026-11-26, `docs/incidents/2026-11-26-producer-silent-loss.md`):
- every message has a delivery callback, and `send()` / `flush()` raise DeliveryFailed for any event Kafka didn't
  take: refused, timed out, never reported, or still queued. It is never a silent success.
- idempotent with `acks=all` and the gapless guarantee: the producer's own retries add no duplicates and can't let a
  later event of a partition be delivered after a lost earlier one.
- `delivery.timeout.ms` bounds the retries.

A resend by the application does add a duplicate, by design, and the posting service recognises it.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from confluent_kafka import KafkaError, KafkaException, Producer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroSerializer
from confluent_kafka.serialization import MessageField, SerializationContext

from app.pipeline import kafka_auth, schemas, topics, trace
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


DEFAULT_DELIVERY_TIMEOUT = 30.0
_NO_REPORT = object()  # an event whose delivery report never arrived


def checkout_producer_config(
    bootstrap: str, delivery_timeout: float = DEFAULT_DELIVERY_TIMEOUT, principal: str = kafka_auth.PRODUCER
) -> dict[str, Any]:
    """Delivery-guarantee settings (ADR-0017):
    - idempotence and `acks=all`: the producer's own retries can't duplicate or reorder within a partition
    - **gapless**: a message lost in a way that could leave a gap fails the producer, so no later message of that
      partition is delivered after it (the gap that let a member's later events post ahead of a lost first one)
    - `delivery.timeout.ms`: retries are bounded, and after it every undelivered message is reported as failed
    """
    if delivery_timeout <= 0:
        raise ValueError("delivery_timeout must be positive")
    return {
        **kafka_auth.client_config(principal, bootstrap),
        "enable.idempotence": True,
        "acks": "all",
        "enable.gapless.guarantee": True,
        "max.in.flight.requests.per.connection": 5,
        "delivery.timeout.ms": int(delivery_timeout * 1000),
        "linger.ms": 5,
    }


def make_checkout_producer(
    bootstrap: str, delivery_timeout: float = DEFAULT_DELIVERY_TIMEOUT, principal: str = kafka_auth.PRODUCER
) -> Producer:
    return Producer(checkout_producer_config(bootstrap, delivery_timeout, principal))


class DeliveryFailed(RuntimeError):
    """Kafka didn't take one or more events. Never reported as a success (incident 2026-11-26).

    `failed`: (event_id, error name) pairs Kafka reported as failed. `undelivered`: events with no delivery report
    at all. `queued`: messages still in the producer's queue when the flush gave up. A fatal error (for example a
    gap under `enable.gapless.guarantee`) leaves the producer unusable: make a new one.
    """

    def __init__(self, failed: list[tuple[str, str]], undelivered: list[str], queued: int = 0, fatal: bool = False):
        self.failed, self.undelivered, self.queued, self.fatal = failed, undelivered, queued, fatal
        parts = []
        if failed:
            parts.append("refused: " + ", ".join(f"{event_id} ({error})" for event_id, error in failed))
        if undelivered:
            parts.append(f"no delivery report for {len(undelivered)} event(s): " + ", ".join(undelivered))
        if queued:
            parts.append(f"{queued} message(s) still queued after the flush timeout")
        super().__init__(
            "events not delivered: " + "; ".join(parts) + (" (fatal: replace the producer)" if fatal else "")
        )


class CheckoutProducer:
    def __init__(
        self,
        producer: Any,
        registry: SchemaRegistryClient | None,
        topic: str = topics.CHECKED_OUT,
        schema: str = "",
        serialize: Callable[[dict[str, Any], SerializationContext], bytes] | None = None,
        delivery_timeout: float = DEFAULT_DELIVERY_TIMEOUT,
    ) -> None:
        """`serialize` replaces the Avro serializer (unit tests); otherwise `registry` is required. Give `producer` the
        settings of `checkout_producer_config` (`make_checkout_producer` does)."""
        self.producer = producer
        self.topic = topic
        self.delivery_timeout = delivery_timeout
        if serialize is None:
            if registry is None:
                raise ValueError("a schema registry client is required")
            serialize = AvroSerializer(registry, schema or schemas.latest(topics.CHECKED_OUT))
        self._serialize = serialize
        self._pending: list[str] = []  # event IDs sent since the last flush
        self._reports: dict[str, KafkaError | None] = {}  # event ID -> its delivery report (None = delivered)

    def send(self, record: dict[str, Any], traceparent: str | None = None, flush: bool = True) -> Sent:
        """Send one event. With `flush` (the default) it returns only once Kafka has taken it, and raises
        DeliveryFailed otherwise. With `flush=False`, call `flush()` afterwards: it raises for any failed event."""
        traceparent = traceparent or trace.new_traceparent()
        event_id = record["event_id"]
        headers = {
            "event_id": event_id,
            "schema_version": SCHEMA_VERSION,
            "correlation_id": record["correlation_id"],
            "traceparent": traceparent,
        }
        value = self._serialize(record, SerializationContext(self.topic, MessageField.VALUE))

        def delivered(error: KafkaError | None, _message: Any) -> None:
            self._reports[event_id] = error

        self._pending.append(event_id)
        try:
            self.producer.produce(
                self.topic,
                key=record["member_number"].encode(),
                value=value,
                headers=list(headers.items()),
                on_delivery=delivered,
            )
        except (KafkaException, BufferError) as exc:
            self._pending.remove(event_id)
            error = exc.args[0] if isinstance(exc, KafkaException) and exc.args else None
            name = error.name() if isinstance(error, KafkaError) else type(exc).__name__
            raise DeliveryFailed([(event_id, name)], []) from exc
        if flush:
            self.flush()
        return Sent(event_id, traceparent)

    def flush(self, timeout: float | None = None) -> None:
        """Wait for every pending event's delivery report. Raises DeliveryFailed unless all of them were delivered."""
        queued = self.producer.flush(self.delivery_timeout + 5 if timeout is None else timeout)
        pending, self._pending = self._pending, []
        reports = {event_id: self._reports.pop(event_id, _NO_REPORT) for event_id in pending}
        failed = [(eid, err.name()) for eid, err in reports.items() if isinstance(err, KafkaError)]
        undelivered = [
            eid for eid, err in reports.items() if err is _NO_REPORT
        ]  # `is`: KafkaError's == can't take this
        if failed or undelivered or queued:
            fatal = any(isinstance(err, KafkaError) and err.fatal() for err in reports.values())
            raise DeliveryFailed(failed, undelivered, queued, fatal)


def synthetic_events(count: int, seed: int) -> list[dict[str, Any]]:
    """Synthetic checkouts for the demo: distinct stays, the same events for the same seed (`seed.stays`). Rates,
    corrections and duplicates: `python -m app.pipeline.loadgen`.

    PR-C fixed this: it used to draw stay IDs at random, so two members could share one, and the second stay was then
    taken for a duplicate (`UNIQUE(stay_id, revision)`) and refused by the ledger (409)."""
    from app.pipeline import seed as seeds  # seed.py uses build_event from this module

    return seeds.stays(count, seed)


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv(override=False)
    parser = argparse.ArgumentParser(description="Send synthetic stay.checked_out events")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    if not 1 <= args.count <= 1000:
        raise SystemExit("--count must be between 1 and 1000 (for rates and more: python -m app.pipeline.loadgen)")
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092").replace("localhost", "127.0.0.1")
    registry = SchemaRegistryClient({"url": os.environ.get("SCHEMA_REGISTRY_URL", "http://127.0.0.1:8081")})
    producer = CheckoutProducer(make_checkout_producer(bootstrap), registry)
    for record in synthetic_events(args.count, args.seed):
        producer.send(record, flush=False)
    producer.flush()
    print(f"sent {args.count} synthetic stay.checked_out event(s) to {producer.topic}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
