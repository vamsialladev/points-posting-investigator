"""Consumer lag and alert rules: pure logic, offline (RFC-0002 Phase 2; S09, S14, S18)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import yaml

from app.ops import alerts, lag
from app.scenarios import plans

T = "stay.checked_out"


def test_lag_is_the_distance_from_the_committed_offset_to_the_end():
    rows = lag.compute({(T, 0): 40, (T, 1): 100, (T, 2): None}, {(T, 0): (0, 100), (T, 1): (0, 100), (T, 2): (10, 25)})
    assert [(r.partition, r.lag) for r in rows] == [(0, 60), (1, 0), (2, 15)]  # nothing committed: all of it waits
    assert lag.total(rows) == 75


def test_lag_never_goes_negative_and_ignores_offsets_that_retention_removed():
    rows = lag.compute({(T, 0): 120, (T, 1): 3}, {(T, 0): (0, 100), (T, 1): (50, 80)})
    assert [r.lag for r in rows] == [0, 30]  # ahead of the end reads as 0; below the low watermark starts at it
    assert lag.compute({}, {(T, 0): (0, 0)})[0].lag == 0 and lag.total([]) == 0


def test_lag_refuses_impossible_watermarks():
    for bad in ((5, 4), (-1, 3)):
        with pytest.raises(ValueError, match="impossible watermarks"):
            lag.compute({}, {(T, 0): bad})


class FakeConsumer:
    """Only the three read calls `lag.read` may use. Anything else would be an AttributeError."""

    def __init__(self, committed: dict[int, int], ends: dict[int, tuple[int, int]], error: object = None) -> None:
        self._committed, self._ends, self._error = committed, ends, error
        self.calls: list[str] = []

    def list_topics(self, topic: str, timeout: float) -> SimpleNamespace:
        self.calls.append("list_topics")
        known = SimpleNamespace(error=self._error, partitions=dict.fromkeys(self._ends))
        return SimpleNamespace(topics={T: known} if topic == T else {})

    def committed(self, partitions: list, timeout: float) -> list:
        self.calls.append("committed")
        for tp in partitions:
            tp.offset = self._committed.get(tp.partition, -1001)  # librdkafka's "no committed offset"
        return partitions

    def get_watermark_offsets(self, tp: object, timeout: float, cached: bool) -> tuple[int, int]:
        assert cached is False, "the live end offset, not a cached one"
        self.calls.append("watermarks")
        return self._ends[tp.partition]  # type: ignore[attr-defined]


def test_read_uses_only_read_calls_and_treats_no_commit_as_none():
    consumer = FakeConsumer({0: 7}, {0: (0, 10), 1: (0, 4)})
    rows = lag.read(consumer, T)
    assert [(r.partition, r.committed, r.lag) for r in rows] == [(0, 7, 3), (1, None, 4)]
    assert set(consumer.calls) == {"list_topics", "committed", "watermarks"}


def test_read_fails_loudly_for_a_topic_it_cannot_see():
    with pytest.raises(LookupError):
        lag.read(FakeConsumer({}, {0: (0, 1)}), "no.such.topic")
    with pytest.raises(LookupError):
        lag.read(FakeConsumer({}, {0: (0, 1)}, error="unknown topic"), T)


QUIET = {
    "posted_in_window": 12,
    "posted_in_previous_window": 9,
    "dead_lettered_in_window": 0,
    "consumer_lag": 0,
    "parked_open": 0,
    "parked_oldest_age_seconds": 0,
    "outbox_unpublished": 0,
    "outbox_oldest_age_seconds": 0,
}


def test_the_committed_rules_load_and_stay_quiet_on_a_healthy_snapshot():
    rules = alerts.load()
    assert {rule.name for rule in rules} >= {plans.ALERT_POSTINGS_DROPPED, "consumer_lag_high", "outbox_backlog"}
    assert all(rule.owner and rule.summary and rule.when for rule in rules)
    evaluations = alerts.evaluate(rules, QUIET)
    assert len(evaluations) == len(rules) and alerts.firing(evaluations) == []
    assert set(QUIET) == alerts.SIGNALS, "the healthy snapshot covers every signal"


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"posted_in_window": 0}, ["postings_dropped"]),  # S18: a burst, then nothing, and nothing else is wrong
        ({"consumer_lag": 40}, ["consumer_lag_high"]),  # S09, S14
        ({"parked_open": 3, "parked_oldest_age_seconds": 45}, ["parked_backlog"]),  # S03, S04, S08, S12
        ({"parked_open": 3, "parked_oldest_age_seconds": 2}, []),  # parked a moment ago: not yet
        ({"dead_lettered_in_window": 1}, ["dead_letters_growing"]),  # S01, S05, S11
        ({"outbox_unpublished": 10, "outbox_oldest_age_seconds": 30}, ["outbox_backlog"]),  # S10
        ({"posted_in_window": 0, "posted_in_previous_window": 2}, []),  # too little traffic before to call it a drop
    ],
)
def test_each_rule_fires_on_its_own_signal_and_only_then(change, expected):
    assert alerts.firing(alerts.evaluate(alerts.load(), {**QUIET, **change})) == expected


def test_a_missing_signal_is_not_evaluated_never_quiet():
    snapshot = {k: v for k, v in QUIET.items() if k != "consumer_lag"}
    by_rule = {e.rule: e for e in alerts.evaluate(alerts.load(), snapshot)}
    assert by_rule["consumer_lag_high"].state == "not_evaluated"
    assert by_rule["consumer_lag_high"].missing == ("consumer_lag",)
    assert by_rule["postings_dropped"].state == "quiet"
    assert dict(by_rule["postings_dropped"].values) == {"posted_in_previous_window": 9.0, "posted_in_window": 12.0}


GOOD = {
    "version": 1,
    "rules": [
        {"name": "r", "owner": "o", "summary": "s", "when": [{"signal": "consumer_lag", "op": ">=", "value": 1}]}
    ],
}


def broken(**change: object) -> dict:
    document = yaml.safe_load(yaml.safe_dump(GOOD))
    rule = document["rules"][0]
    for key, value in change.items():
        if key in ("signal", "op", "value"):
            rule["when"][0][key] = value
        elif key == "extra":
            rule[str(value)] = 1
        elif key == "top":
            document.update(value)  # type: ignore[arg-type]
        else:
            rule[key] = value
    return document


@pytest.mark.parametrize(
    "document",
    [
        broken(signal="consumer_lagg"),
        broken(op="=>"),
        broken(value="ten"),
        broken(value=True),
        broken(owner=""),
        broken(when=[]),
        broken(extra="severity"),
        broken(top={"version": 2}),
        broken(top={"rules": []}),
        {**GOOD, "rules": GOOD["rules"] * 2},  # the same name twice
        [],
    ],
)
def test_the_loader_refuses_what_it_does_not_understand(document):
    with pytest.raises(ValueError):
        alerts.parse(document)


def test_a_good_document_parses():
    (rule,) = alerts.parse(GOOD)
    assert rule.when == (alerts.Condition("consumer_lag", ">=", 1.0),)
