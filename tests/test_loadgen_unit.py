"""Seeds and the load generator, offline (PIPE-09, PIPE-10). Synthetic data."""

from __future__ import annotations

from collections import Counter

import pytest

from app.pipeline import seed
from app.pipeline.events import validate
from app.pipeline.loadgen import MAX_EVENTS, MAX_RATE, LoadSpec, Pacer, Planned, plan_load, run


def valid(record):
    return validate(record, {"event_id": record["event_id"], "schema_version": "1"})


# ---------- seeds ----------


def test_members_have_stage9_shapes_and_seeded_tiers():
    people = seed.members(50, seed=3)
    assert [p.member_number for p in people[:2]] == ["GR-00001", "GR-00002"]
    assert {p.tier for p in people} <= set(seed.TIERS) and {p.tenant for p in people} == {"hg-demo"}
    assert people == seed.members(50, seed=3)
    with pytest.raises(ValueError):
        seed.members(0, seed=1)


def test_stays_are_valid_distinct_and_exactly_repeatable():
    a, b = seed.stays(300, seed=5), seed.stays(300, seed=5)
    assert a == b  # event IDs included: a rerun sends real duplicates
    assert len({r["stay_id"] for r in a}) == 300  # no two stays share an ID
    assert {r["stay_id"][:2] for r in a} == {"BR", "ML"}
    for record in a:
        assert valid(record).revision == 1
    assert seed.stays(300, seed=6)[0]["event_id"] != a[0]["event_id"]


def test_stay_numbers_that_do_not_fit_are_refused():
    assert seed.stays(2, seed=1, first_stay=9_999)[0]["stay_id"] == "BR-9999"
    with pytest.raises(ValueError, match="don't fit"):
        seed.stays(4, seed=1, first_stay=9_999)  # needs BR-10000


def test_a_correction_keeps_the_stay_and_member_with_a_new_event_and_revision():
    import random

    original = seed.stays(1, seed=2)[0]
    fixed = seed.correction_of(original, random.Random(1))
    assert (fixed["stay_id"], fixed["member_number"], fixed["revision"]) == (
        original["stay_id"],
        original["member_number"],
        2,
    )
    assert fixed["event_id"] != original["event_id"] and fixed["room_rate_cents"] != original["room_rate_cents"]
    assert valid(fixed).revision == 2


# ---------- the plan ----------


def test_the_plan_has_every_original_once_and_corrections_after_their_original():
    plan = plan_load(LoadSpec(count=400, rate=50, seed=9, corrections=0.1, duplicates=0.05))
    kinds = Counter(p.kind for p in plan)
    assert kinds["original"] == 400 and kinds["correction"] > 0 and kinds["duplicate"] > 0
    first_seen = {}
    for position, event in enumerate(plan):
        key = event.record["stay_id"]
        if event.kind == "original":
            first_seen[key] = position
        else:
            assert first_seen[key] < position, f"{event.kind} of {key} before its original"
    duplicates = [p.record["event_id"] for p in plan if p.kind == "duplicate"]
    originals = {p.record["event_id"] for p in plan if p.kind == "original"}
    assert set(duplicates) <= originals  # a duplicate is the same event, the same event ID


def test_the_plan_is_repeatable():
    spec = LoadSpec(count=100, rate=10, seed=4, corrections=0.2, duplicates=0.2)
    assert plan_load(spec) == plan_load(spec)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"count": 10, "rate": 0},
        {"count": 10, "rate": MAX_RATE + 1},
        {"count": MAX_EVENTS + 1, "rate": 10},
        {"count": MAX_EVENTS, "rate": 10, "corrections": 0.5},  # corrections count toward the cap too
        {"count": 0, "rate": 10},
        {"count": 10, "rate": 10, "duplicates": 1.5},
    ],
)
def test_the_hard_caps_refuse_rather_than_trim(kwargs):
    with pytest.raises(ValueError):
        LoadSpec(**kwargs)


# ---------- pacing ----------


class FakeClock:
    def __init__(self):
        self.now, self.slept = 100.0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(round(seconds, 6))
        self.now += seconds


def test_the_pacer_spaces_events_at_the_rate():
    clock = FakeClock()
    pacer = Pacer(4.0, clock, clock.sleep)
    for _ in range(5):
        pacer.wait()
    assert clock.slept == [0.25, 0.25, 0.25, 0.25]  # the first goes at once, then one every 1/4 s
    assert clock.now == pytest.approx(101.0)


def test_a_slow_send_is_not_followed_by_a_burst_beyond_the_schedule():
    clock = FakeClock()
    pacer = Pacer(2.0, clock, clock.sleep)
    pacer.wait()  # event 0 at t=100
    clock.now += 2.0  # a 2 s stall: events 1..4 were due by 100.5 .. 102.0
    assert [pacer.wait() for _ in range(4)] == [0.0, 0.0, 0.0, 0.0]  # late ones go at once...
    assert pacer.wait() == pytest.approx(0.5)  # ...and the next is back on schedule (102.5), not earlier


class FakeProducer:
    def __init__(self):
        self.sent = []

    def send(self, record):
        self.sent.append(record["event_id"])


def test_run_sends_the_plan_in_order_and_counts_each_kind():
    clock = FakeClock()
    plan = [Planned("original", {"event_id": "a"}), Planned("duplicate", {"event_id": "a"})]
    plan.append(Planned("correction", {"event_id": "b"}))
    producer = FakeProducer()
    result = run(plan, producer, Pacer(10.0, clock, clock.sleep), clock=clock)
    assert producer.sent == ["a", "a", "b"]
    assert (result.sent, result.originals, result.duplicates, result.corrections) == (3, 1, 1, 1)
    assert result.seconds == pytest.approx(0.2)
