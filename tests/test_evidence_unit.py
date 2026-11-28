"""The evidence model, the fixed queries and the snapshot, offline (RFC-0002 Phase 3). The roles and the broker are
tested for real in tests/test_evidence_postgres.py and the scenario tests."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.evidence import model, snapshot, store, topics
from app.scenarios import catalog

T0 = datetime(2026, 11, 28, 2, 0, tzinfo=UTC)


def test_an_evidence_id_starts_with_its_kind_and_long_text_is_cut():
    item = model.evidence("log", "42", T0, message="x" * 1000, level="WARNING")
    assert item.id == "log:42" and item.at == T0.isoformat()
    assert len(item.data["message"]) == model.TEXT_LIMIT + 1 and item.data["message"].endswith("…")
    assert item.data["level"] == "WARNING"
    for bad in (lambda: model.Evidence("42", "log", None), lambda: model.Evidence("x:1", "rumour", None)):
        with pytest.raises(ValueError):
            bad()


def test_every_free_text_field_the_queries_return_is_marked_untrusted():
    """A field that can hold text someone else wrote must be in UNTRUSTED, so a reader of the evidence knows."""
    free_text = {"message", "last_error", "correlation_id", "question", "old_value", "new_value"}
    selected = set()
    for _database, _kind, sql, _id, _time in store.QUERIES.values():
        selected |= set(re.findall(r"\b([a-z_]+)\b", sql.split(" FROM ")[0]))
    assert free_text <= selected, "the queries do return these"
    assert free_text <= model.UNTRUSTED
    assert {"error_detail", "body"} <= model.UNTRUSTED  # dead-letter headers and runbook text


def test_every_query_is_one_bounded_select_and_none_asks_for_raw_bytes():
    for name, (database, kind, sql, id_column, time_column) in store.QUERIES.items():
        assert database in ("posting", "ledger", "ops") and kind in model.KINDS, name
        assert sql.startswith("SELECT ") and sql.rstrip().endswith("LIMIT :limit"), name
        assert ":since" in sql and ";" not in sql, name
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|TRUNCATE|ALTER|DROP|GRANT|COPY|CREATE)\b", sql), name
        assert "raw_value" not in sql and "raw_key" not in sql, name
        assert re.search(rf"\b{id_column}\b", sql) and (time_column is None or time_column in sql), name


class FakeEngine:
    def __init__(self, rows: list[dict]) -> None:
        self.rows, self.seen = rows, []

    def connect(self):
        engine = self

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, statement, params):
                engine.seen.append((str(statement), params))
                return [SimpleNamespace(_mapping=row) for row in engine.rows[: params["limit"]]]

        return Conn()


def a_store(rows: list[dict]) -> tuple[store.EvidenceStore, FakeEngine]:
    engine = FakeEngine(rows)
    return store.EvidenceStore({"posting": engine, "ledger": engine, "ops": engine}), engine


def log_row(n: int, message: str = "retrying") -> dict:
    row = {"id": n, "logged_at": T0 + timedelta(seconds=n), "service": "posting", "level": "WARNING"}
    return {**row, "logger": "posting", "message": message, "correlation_id": None, "trace_id": None, "event_id": None}


def test_a_read_binds_its_parameters_and_says_when_there_was_more():
    evidence_store, engine = a_store([log_row(n) for n in range(5)])
    items, more = evidence_store.read("logs", T0, limit=3)
    assert [item.id for item in items] == ["log:0", "log:1", "log:2"] and more is True
    assert engine.seen[0][1] == {"since": T0, "limit": 4}, "one extra row, to know whether the limit was hit"
    assert items[0].at == T0.isoformat() and "id" not in items[0].data and "logged_at" not in items[0].data
    items, more = evidence_store.read("logs", T0, limit=10)
    assert len(items) == 5 and more is False


def test_planted_text_comes_back_as_a_value_and_never_reaches_the_query():
    evidence_store, engine = a_store([log_row(1, catalog.INJECTION_LOG_MESSAGE)])
    (item,), _ = evidence_store.read("logs", T0)
    assert item.data["message"] == catalog.INJECTION_LOG_MESSAGE
    assert "SYSTEM:" not in engine.seen[0][0] and "alert noise" not in engine.seen[0][0]


def test_a_read_refuses_an_unknown_name_and_a_limit_out_of_range():
    evidence_store, _ = a_store([])
    for call in (
        lambda: evidence_store.read("ledger_balance", T0),
        lambda: evidence_store.read("logs", T0, limit=0),
        lambda: evidence_store.read("logs", T0, limit=store.MAX_LIMIT + 1),
        lambda: store.EvidenceStore({"posting": None}),
        lambda: store.engines_from_env({}),
    ):
        with pytest.raises(ValueError):
            call()


class Message:
    def __init__(
        self, value: bytes, headers: dict[str, str], when: datetime, offset: int = 7, key: bytes = b"GR-30000"
    ):
        self._value, self._headers, self._when, self._offset, self._key = value, headers, when, offset, key

    def headers(self):
        return [(name, text.encode()) for name, text in self._headers.items()]

    def timestamp(self):
        return (1, int(self._when.timestamp() * 1000))

    def key(self):
        return self._key

    def value(self):
        return self._value

    def partition(self):
        return 2

    def offset(self):
        return self._offset


def decode(value: bytes, topic: str) -> dict:
    if not value.startswith(b"{"):
        raise ValueError("not Avro")
    record = json.loads(value)
    record["occurred_at"] = datetime.fromisoformat(record["occurred_at"])
    return record


def record(occurred: datetime) -> bytes:
    return json.dumps({"event_id": "e-1", "stay_id": "BR-0100", "member_number": "GR-30000", "revision": 1,
                       "occurred_at": occurred.isoformat(), "room_rate_cents": 15000}).encode()  # fmt: skip


def test_an_event_carries_its_own_time_next_to_the_brokers_so_a_clock_skew_shows():
    headers = {"event_id": "e-1", "schema_version": "1", "correlation_id": "corr-1", "traceparent": "00-…"}
    skewed = topics.describe_message(
        "stay.checked_out", Message(record(T0 + timedelta(hours=6)), headers, T0), decode, False
    )
    normal = topics.describe_message(
        "stay.checked_out", Message(record(T0 - timedelta(seconds=1)), headers, T0), decode, False
    )
    assert skewed.id == "event:stay.checked_out/2@7" and skewed.at == T0.isoformat()
    assert skewed.data["occurred_minus_broker_seconds"] == 6 * 3600.0
    assert normal.data["occurred_minus_broker_seconds"] == -1.0
    assert skewed.data["key"] == "GR-30000" and skewed.data["stay_id"] == "BR-0100" and skewed.data["decoded"] is True
    assert "room_rate_cents" not in skewed.data and "traceparent" not in skewed.data, "only the fields that identify it"


def test_an_undecodable_event_says_so_and_its_bytes_are_never_returned():
    item = topics.describe_message(
        "stay.checked_out", Message(b"\x00not-avro secret", {"event_id": "e-9"}, T0), decode, False
    )
    assert item.data["decoded"] is False and item.data["decode_error"] == "ValueError"
    assert "secret" not in json.dumps(dict(item.data)) and item.data["event_id"] == "e-9"


def test_a_dead_letter_carries_its_failure_headers_and_planted_text_stays_a_value():
    failure = {"error_class": "ledger_rejected_422", "error_detail": "rejected_422", "attempt": "5"}
    headers = {
        "event_id": "e-5",
        "correlation_id": catalog.INJECTION_CORRELATION_ID,
        **failure,
        "original_offset": "21",
    }
    item = topics.describe_message("stay.checked_out.dlq", Message(b"x", headers, T0), None, True)
    assert item.kind == "dead_letter" and item.id == "dead_letter:stay.checked_out.dlq/2@7"
    assert (item.data["error_class"], item.data["attempt"], item.data["original_offset"]) == (
        "ledger_rejected_422",
        "5",
        "21",
    )
    assert item.data["correlation_id"] == catalog.INJECTION_CORRELATION_ID
    assert "decoded" not in item.data, "no decoder was given, so nothing was decoded"
    plain = topics.describe_message("stay.checked_out", Message(b"x", headers, T0), None, False)
    assert "error_class" not in plain.data, "failure headers are read on the dead-letter topic only"


class FakeStore:
    def __init__(self, more: tuple[str, ...] = ()) -> None:
        self.more = more

    def read(self, name: str, since: datetime, limit: int):
        kind = store.QUERIES[name][1]
        return [model.evidence(kind, f"{name}-1", since)], name in self.more


class FakeReader:
    group = "posting-service"

    def messages(self, topic: str, *, dead_letter: bool, limit: int):
        kind = "dead_letter" if dead_letter else "event"
        old = model.evidence(kind, f"{topic}/0@1", T0 - timedelta(hours=1))
        new = model.evidence(kind, f"{topic}/0@2", T0 + timedelta(seconds=5))
        return [old, new], False

    def lag(self, topic: str):
        return [model.evidence("lag", f"posting-service/{topic}/0@x", T0, lag=3)]


def test_a_snapshot_reads_everything_drops_old_messages_and_names_what_was_cut():
    taken = snapshot.collect(FakeStore(more=("logs",)), FakeReader(), T0, now=T0 + timedelta(minutes=1))
    kinds = [item.kind for item in taken.items]
    assert kinds.count("event") == 2 and kinds.count("dead_letter") == 1 and kinds.count("lag") == 1
    assert all("@1" not in item.id for item in taken.items), "messages older than the window are left out"
    assert taken.truncated == ("logs",) and taken.since == T0.isoformat()
    assert len(taken.ids()) == len(taken.items), "an id is cited once"
    again = model.Snapshot.from_json(json.loads(json.dumps(taken.to_json())))
    assert again == taken, "a snapshot survives being written and read back"
    assert [item.id for item in taken.of("lag")] == ["lag:posting-service/stay.checked_out/0@x"]


def test_a_snapshot_without_a_topic_reader_holds_the_stored_evidence_only():
    taken = snapshot.collect(FakeStore(), None, T0)
    assert {item.kind for item in taken.items} == {kind for _d, kind, *_ in store.QUERIES.values()}
    assert taken.truncated == ()
