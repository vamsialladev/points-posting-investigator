"""Smoke test of the running relay container (`docker compose --profile core`): a row written to the stack's own
outbox is published to `points.posted`, and /metrics answers.

Needs TEST_DATABASE_URL (for the host), TEST_POSTING_DB_PASSWORD and TEST_RELAY_METRICS_URL.
scripts\\test_integration.ps1 maps them without printing them. It writes one synthetic row, marked `smoke`, to the
stack's outbox.
"""

from __future__ import annotations

import os
import time
import uuid

import httpx
import pytest
from sqlalchemy import create_engine, insert, select
from sqlalchemy.engine import make_url

from app.db.roles import Database, runtime_url
from app.pipeline import topics, trace
from app.pipeline.tables import outbox
from tests.relay_helpers import payload

pytestmark = [pytest.mark.postgres, pytest.mark.kafka]


def test_the_running_relay_publishes_a_row_and_serves_metrics():
    raw, password, metrics_url = (
        os.environ.get("TEST_DATABASE_URL"),
        os.environ.get("TEST_POSTING_DB_PASSWORD"),
        os.environ.get("TEST_RELAY_METRICS_URL"),
    )
    if not (raw and password and metrics_url):
        pytest.skip(
            "TEST_DATABASE_URL, TEST_POSTING_DB_PASSWORD or TEST_RELAY_METRICS_URL not set: run scripts\\stack.ps1 up, "
            "then scripts\\test_integration.ps1"
        )
    admin = make_url(raw)
    engine = create_engine(
        runtime_url(Database("posting"), password, host=admin.host or "localhost", port=admin.port or 5432)
    )
    record = payload("GR-09999", 9999) | {"correlation_id": f"smoke-{uuid.uuid4()}"}
    try:
        with engine.begin() as conn:
            row_id = conn.execute(
                insert(outbox)
                .values(
                    topic=topics.POINTS_POSTED,
                    message_key="GR-09999",
                    payload=record,
                    headers={"correlation_id": record["correlation_id"], "schema_version": "1", "smoke": "true"},
                    trace_context={"traceparent": trace.new_traceparent()},
                )
                .returning(outbox.c.id)
            ).scalar_one()
        deadline = time.monotonic() + 60
        status = None
        while time.monotonic() < deadline:
            with engine.connect() as conn:
                status = conn.execute(select(outbox.c.status).where(outbox.c.id == row_id)).scalar_one()
            if status == "published":
                break
            time.sleep(0.5)
        assert status == "published", f"the relay container didn't publish the row (status {status})"
    finally:
        engine.dispose()
    text = httpx.get(metrics_url.replace("://localhost", "://127.0.0.1"), timeout=5).text
    for name in ("outbox_unpublished_rows", "outbox_oldest_unpublished_age_seconds", "outbox_dead_rows"):
        assert name in text
