"""Smoke test of the running containers end to end: producer -> `stay.checked_out` -> posting container -> ledger
container -> outbox -> relay container -> `points.posted`.

It sends one synthetic event (member GR-09998, a fresh stay ID) to the stack's own topic, and needs
TEST_DATABASE_URL, TEST_POSTING_DB_PASSWORD, TEST_KAFKA_BOOTSTRAP_SERVERS and TEST_SCHEMA_REGISTRY_URL
(scripts\\test_integration.ps1 maps them without printing them).
"""

from __future__ import annotations

import os
import random
import time
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url

from app.db.roles import Database, runtime_url
from app.pipeline import topics
from app.pipeline.producer import build_event
from app.pipeline.tables import outbox, posting
from tests.posting_helpers import checkout_producer

pytestmark = [pytest.mark.postgres, pytest.mark.kafka]


def test_an_event_flows_through_the_running_containers(kafka, registry):
    raw, password = os.environ.get("TEST_DATABASE_URL"), os.environ.get("TEST_POSTING_DB_PASSWORD")
    if not (raw and password):
        pytest.skip("TEST_DATABASE_URL or TEST_POSTING_DB_PASSWORD not set: run scripts\\test_integration.ps1")
    admin = make_url(raw)
    engine = create_engine(
        runtime_url(Database("posting"), password, host=admin.host or "localhost", port=admin.port or 5432)
    )
    # A stay the stack hasn't posted before: earlier smoke runs stay in its database, and reusing a stay ID would be
    # (correctly) refused as a duplicate.
    with engine.connect() as conn:
        used = set(conn.execute(select(posting.c.stay_id).where(posting.c.stay_id.like("ML-%"))).scalars())
    free = [f"ML-{n:04d}" for n in range(1000, 10000) if f"ML-{n:04d}" not in used]
    assert free, "no unused smoke-test stay ID left: reset the stack's data with scripts\\stack.ps1 reset"
    stay_id = random.choice(free)
    record = build_event(
        member_number="GR-09998", stay_id=stay_id, check_in=date(2026, 11, 20), nights=1, room_rate_cents=12_345
    )
    sent = checkout_producer(kafka, registry, topics.CHECKED_OUT).send(record)
    try:
        status, deadline = None, time.monotonic() + 90
        while time.monotonic() < deadline:
            with engine.connect() as conn:
                posted = conn.execute(
                    select(posting.c.ledger_entry_id).where(posting.c.event_id == sent.event_id)
                ).first()
                status = conn.execute(
                    select(outbox.c.status).where(outbox.c.payload["source_event_id"].astext == sent.event_id)
                ).scalar()
            if posted and status == "published":
                break
            time.sleep(0.5)
        assert posted is not None, "the posting container didn't post the event"
        assert status == "published", f"the relay container didn't publish it (outbox status {status})"
        assert posted.ledger_entry_id.startswith("L-")
    finally:
        engine.dispose()
