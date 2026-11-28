"""The read-only roles on real Postgres: they can read the evidence, and Postgres refuses everything else.

The read-only guarantee of RFC-0002 must not rest on the investigator's code. These tests log in as the three
`*_investigator` roles (in the `test_` databases) and try what they must not be able to do.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from psycopg import errors
from sqlalchemy import create_engine

from app.db.roles import INVESTIGATOR, RUNTIME_ROLES, Database
from app.evidence.store import QUERIES, EvidenceStore
from app.scenarios import catalog
from tests.infra import LEDGER, POSTING, PREFIX, admin_connect, role_url, runtime_connect

pytestmark = pytest.mark.postgres
OPS = Database("ops", PREFIX)
DATABASES = {"posting": POSTING, "ledger": LEDGER, "ops": OPS}
SINCE = datetime.now(UTC) - timedelta(hours=1)


@pytest.fixture
def evidence_store(admin, passwords, host) -> Iterator[EvidenceStore]:
    with admin_connect(admin, POSTING) as conn:
        conn.execute("TRUNCATE posting, outbox, parked_event, skipped_event RESTART IDENTITY")
        conn.execute(
            "INSERT INTO posting (event_id, stay_id, revision, member_number, stay_points, credited_points,"
            " ledger_entry_id, correlation_id) VALUES ('e-1', 'BR-0001', 1, 'GR-00001', 1500, 1500, 'L-0000001', 'c-1')"
        )
        conn.execute(
            "INSERT INTO parked_event (event_id, member_number, stay_id, revision, raw_key, raw_value, raw_headers,"
            " source_topic, source_partition, source_offset, error_class, last_error)"
            " VALUES ('e-2', 'GR-00002', 'ML-0001', 1, 'GR-00002', 'the raw bytes', %s, 'stay.checked_out', 0, 5,"
            " 'ledger_unauthorized', 'unauthorized')",
            ('{"correlation_id": "' + catalog.INJECTION_CORRELATION_ID + '"}',),
        )
    with admin_connect(admin, LEDGER) as conn:
        conn.execute("TRUNCATE credits")
        conn.execute(
            "INSERT INTO credits (entry_id, idempotency_key, request_hash, member_number, stay_id, points,"
            " correlation_id) VALUES ('L-0000001', 'BR-0001:1', 'h', 'GR-00001', 'BR-0001', 1500, 'c-1')"
        )
    with admin_connect(admin, OPS) as conn:
        conn.execute("TRUNCATE log_event, change_event, member_question, alert_evaluation RESTART IDENTITY")
        conn.execute(
            "INSERT INTO log_event (service, level, logger, message) VALUES"
            " ('posting', 'WARNING', 'posting', %s), ('posting', 'INFO', 'posting', 'posting service started'),"
            " ('posting', 'INFO', 'httpx', 'HTTP Request: POST http://ledger:8020/v1/credits')",
            (catalog.INJECTION_LOG_MESSAGE,),
        )
        conn.execute(
            "INSERT INTO change_event (service, setting, old_value, new_value, source)"
            " VALUES ('posting', 'LEDGER_TIMEOUT_SECONDS', '5.0', '0.001', 'scenario')"
        )
    engines = {base: create_engine(role_url(db, passwords, host, INVESTIGATOR)) for base, db in DATABASES.items()}
    yield EvidenceStore(engines)
    for engine in engines.values():
        engine.dispose()


def test_every_stored_read_works_as_the_read_only_roles(evidence_store):
    found = {name: evidence_store.read(name, SINCE)[0] for name in QUERIES}
    assert [i.id for i in found["postings"]] == ["posting:e-1"]
    assert [i.id for i in found["credits"]] == ["credit:L-0000001"]
    (parked,) = found["parked"]
    assert parked.data["error_class"] == "ledger_unauthorized"
    assert parked.data["correlation_id"] == catalog.INJECTION_CORRELATION_ID, "planted text is just a value"
    assert "raw_value" not in parked.data and "raw_key" not in parked.data
    assert [i.data["message"] for i in found["logs"]] == [catalog.INJECTION_LOG_MESSAGE]
    assert [i.data["message"] for i in found["lifecycle_logs"]] == ["posting service started"], "request lines left out"
    assert [(i.data["old_value"], i.data["new_value"]) for i in found["changes"]] == [("5.0", "0.001")]
    assert found["outbox"] == [] and found["skipped"] == [] and found["questions"] == [] and found["alerts"] == []


WRITES = {
    "posting": [
        "INSERT INTO posting (event_id, stay_id, revision, member_number, stay_points, credited_points,"
        " ledger_entry_id, correlation_id) VALUES ('x', 'BR-0009', 1, 'GR-00009', 1, 1, 'L-0000009', 'c')",
        "UPDATE posting SET credited_points = 0",
        "DELETE FROM posting",
        "UPDATE parked_event SET status = 'pending'",
        "UPDATE outbox SET status = 'pending'",
        "DELETE FROM parked_event",
        "TRUNCATE skipped_event",
        "DROP TABLE posting",
        "CREATE TABLE scratch (n int)",
    ],
    "ledger": [
        "INSERT INTO credits (entry_id, idempotency_key, request_hash, member_number, stay_id, points, correlation_id)"
        " VALUES ('L-0000099', 'BR-0099:1', 'h', 'GR-00099', 'BR-0099', 999999, 'c')",
        "UPDATE credits SET points = points + 1",
        "DELETE FROM credits",
    ],
    "ops": [
        "INSERT INTO log_event (service, level, logger, message) VALUES ('s', 'INFO', 'l', 'm')",
        "INSERT INTO change_event (service, setting, old_value, new_value, source)"
        " VALUES ('s', 'k', 'a', 'b', 'operator')",
        "DELETE FROM log_event",
        "UPDATE runbook_section SET body = 'rewritten'",
        "INSERT INTO alert_evaluation (rule, state) VALUES ('r', 'quiet')",
    ],
}


@pytest.mark.parametrize(("base", "statement"), [(base, sql) for base, many in WRITES.items() for sql in many])
def test_postgres_refuses_every_write_by_an_investigator_role(evidence_store, passwords, host, base, statement):
    """Refused twice over: the role has no such grant, and its transactions are read-only."""
    refused = (errors.InsufficientPrivilege, errors.ReadOnlySqlTransaction)
    with runtime_connect(DATABASES[base], passwords, host, INVESTIGATOR) as conn, pytest.raises(refused):
        conn.execute(statement)


def test_the_raw_bytes_of_a_parked_event_cannot_be_read(evidence_store, passwords, host):
    with runtime_connect(POSTING, passwords, host, INVESTIGATOR) as conn:
        for column in ("raw_value", "raw_key", "*"):
            with pytest.raises(errors.InsufficientPrivilege):
                conn.execute(f"SELECT {column} FROM parked_event")
        assert conn.execute("SELECT event_id, error_class FROM parked_event").fetchall() == [
            ("e-2", "ledger_unauthorized")
        ]


def test_every_investigator_session_starts_read_only_and_stays_refused_if_it_switches_that_off(passwords, host):
    for base, database in DATABASES.items():
        with runtime_connect(database, passwords, host, INVESTIGATOR) as conn:
            assert conn.execute("SHOW default_transaction_read_only").fetchone() == ("on",), base
            assert conn.execute("SHOW transaction_read_only").fetchone() == ("on",), base
            # A session may turn the setting off for itself; the grants are what then still refuses the write.
            conn.execute("SET default_transaction_read_only = off")
            table = next(iter(RUNTIME_ROLES[base][-1].grants)).split(" ", 1)[1]
            with pytest.raises(errors.InsufficientPrivilege):
                conn.execute(f"DELETE FROM {table}")


def test_an_investigator_role_cannot_use_a_sequence_or_reach_another_database(passwords, host):
    refused = (errors.InsufficientPrivilege, errors.ReadOnlySqlTransaction)
    with runtime_connect(POSTING, passwords, host, INVESTIGATOR) as conn, pytest.raises(refused):
        conn.execute("SELECT nextval('outbox_id_seq')")
    url = role_url(POSTING, passwords, host, INVESTIGATOR)
    engine = create_engine(url.set(database=LEDGER.name))  # the posting reader's name on the ledger's database
    with pytest.raises(Exception, match=r"permission denied for database|CONNECT"):
        engine.connect()
    engine.dispose()
