"""Fixtures and helpers shared by the posting-service and retry-worker real-stack tests (loaded by conftest.py).

- `db`: engines for test_posting (posting service and relay roles) and test_ledger, with their tables emptied
- `ledger`: the real ledger app over HTTP on a free local port, with a fresh token
- `scratch`: throwaway input, output and DLQ topics for one test
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Iterator
from datetime import date

import pytest
from confluent_kafka.admin import AdminClient
from sqlalchemy import Engine, create_engine

from app.pipeline import topics
from app.pipeline.events import ledger_key, points_for, validate
from app.pipeline.producer import build_event
from tests.infra import LEDGER, POSTING, admin_connect, role_url
from tests.posting_helpers import ledger_server
from tests.test_kafka_stack import drop_subject


@pytest.fixture
def db(admin, passwords, host) -> Iterator[dict[str, Engine]]:
    with admin_connect(admin, POSTING) as conn:
        conn.execute("TRUNCATE posting, outbox, parked_event, skipped_event RESTART IDENTITY")
    with admin_connect(admin, LEDGER) as conn:
        conn.execute("TRUNCATE credits")
    engines = {
        "posting": create_engine(role_url(POSTING, passwords, host, "app"), pool_size=10),
        "relay": create_engine(role_url(POSTING, passwords, host, "relay")),
        "ledger": create_engine(role_url(LEDGER, passwords, host), pool_size=10),
    }
    yield engines
    for engine in engines.values():
        engine.dispose()


@pytest.fixture
def ledger(db) -> Iterator[tuple[str, str]]:
    token = secrets.token_urlsafe(18)
    with ledger_server(db["ledger"], token) as url:
        yield url, token


@pytest.fixture
def scratch(kafka, registry) -> Iterator[dict[str, str]]:
    tag = uuid.uuid4().hex[:10]
    names = {"input": f"test.in.{tag}", "output": f"test.out.{tag}", "dlq": f"test.dlq.{tag}"}
    topics.ensure_topics(kafka, tuple(topics.TopicSpec(name) for name in names.values()))
    yield names
    AdminClient({"bootstrap.servers": kafka}).delete_topics(list(names.values()), operation_timeout=30)
    for name in names.values():
        drop_subject(registry, f"{name}-value")


def stay(member: str, n: int, **changes) -> dict:
    """A synthetic stay: stay ID from n (odd: Beach Resort BR-, even: Mountain Lodge ML-). Any field can be changed."""
    prefix, prop = ("BR", "beach-resort") if n % 2 else ("ML", "mountain-lodge")
    fields = {
        "member_number": member,
        "stay_id": f"{prefix}-{n:04d}",
        "property": prop,
        "check_in": date(2026, 11, 14),
        "nights": 2,
        "room_rate_cents": 20_000 + n,
        **changes,
    }
    return build_event(**fields)


def expected_credits(*records: dict) -> dict[str, int]:
    events = [validate(r, {"event_id": r["event_id"], "schema_version": "1"}) for r in records]
    return {ledger_key(e): points_for(e) for e in events}
