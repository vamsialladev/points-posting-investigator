"""The long-running loops survive a failed cycle, stop when asked, and let a test's crash through (offline).

Each loop (posting consumer, relay, retry worker) wraps `run_once()`: an unexpected error is logged and the loop
waits and goes on (nothing was committed, so the next cycle retries); the crash a test injects is re-raised; an
idle cycle waits `poll_interval` before the next one.
"""

from __future__ import annotations

import threading

import pytest

from app.pipeline.posting import PostingConsumer, PostingCrash
from app.pipeline.relay import CycleResult, Relay, RelayConfig, RelayCrash, RelayMetrics
from app.pipeline.retry import RetryConfig, RetryCrash, RetryCycle, RetryWorker


class ScriptedStop(threading.Event):
    """A stop event that sets itself after `cycles` waits, so a loop runs a known number of times."""

    def __init__(self, cycles: int) -> None:
        super().__init__()
        self.left, self.waits = cycles, []

    def wait(self, timeout: float | None = None) -> bool:
        self.waits.append(timeout)
        self.left -= 1
        if self.left <= 0:
            self.set()
        return self.is_set()


def scripted(results):
    """run_once that returns (or raises) each scripted result in turn, then keeps returning the last."""
    calls = []

    def run_once(*_args, **_kwargs):
        calls.append(1)
        result = results[min(len(calls), len(results)) - 1]
        if isinstance(result, BaseException):
            raise result
        return result

    return run_once, calls


# ---------- the posting consumer ----------


def test_the_posting_loop_logs_a_failed_cycle_and_goes_on(caplog):
    # In production consumer.poll() blocks for up to a second, so the loop only waits itself after a failure. Here the
    # second, successful cycle ends the run.
    loop = PostingConsumer(service=object(), consumer=object())
    stop = ScriptedStop(cycles=99)
    calls = []

    def run_once():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database hiccup")
        stop.set()

    loop.run_once = run_once
    loop.run(stop)
    assert len(calls) == 2  # it went on after the failure
    assert stop.waits == [1.0]
    assert "posting cycle failed" in caplog.text


def test_the_posting_loop_lets_a_test_crash_through():
    loop = PostingConsumer(service=object(), consumer=object())
    loop.run_once, _ = scripted([PostingCrash("after_db_commit_before_offset_commit")])
    with pytest.raises(PostingCrash):
        loop.run(ScriptedStop(cycles=5))


def test_the_posting_loop_stops_when_asked():
    loop = PostingConsumer(service=object(), consumer=object())
    loop.run_once, calls = scripted([None])
    stop = ScriptedStop(cycles=1)
    stop.set()
    loop.run(stop)
    assert calls == []


# ---------- the relay ----------


def relay():
    return Relay(
        store=object(),
        producer=object(),
        serializer=lambda t, p: b"",
        config=RelayConfig(relay_id="r"),
        metrics=RelayMetrics(),
    )


def test_the_relay_waits_after_an_idle_cycle_and_after_a_failed_one(caplog):
    r = relay()
    r.run_once, calls = scripted([CycleResult(claimed=2), CycleResult(), RuntimeError("broker hiccup"), CycleResult()])
    stop = ScriptedStop(cycles=3)
    r.run(stop, poll_interval=0.25)
    assert len(calls) == 4  # a busy cycle runs again at once; idle and failed cycles wait
    assert stop.waits == [0.25, 0.25, 0.25]
    assert "cycle failed" in caplog.text


def test_the_relay_lets_a_test_crash_through():
    r = relay()
    r.run_once, _ = scripted([RelayCrash("after_publish_before_mark")])
    with pytest.raises(RelayCrash):
        r.run(ScriptedStop(cycles=5))


# ---------- the retry worker ----------


def worker():
    return RetryWorker(
        parked=object(),
        postings=object(),
        ledger=object(),
        deserialize=lambda v, t: {},
        dead_letters=object(),
        config=RetryConfig(worker_id="w"),
    )


def test_the_retry_worker_waits_after_an_idle_cycle_and_after_a_failed_one(caplog):
    w = worker()
    w.run_once, calls = scripted([RetryCycle(claimed=3), RetryCycle(), RuntimeError("database hiccup"), RetryCycle()])
    stop = ScriptedStop(cycles=3)
    w.run(stop, poll_interval=0.5)
    assert len(calls) == 4
    assert stop.waits == [0.5, 0.5, 0.5]
    assert "retry cycle failed" in caplog.text


def test_the_retry_worker_lets_a_test_crash_through():
    w = worker()
    w.run_once, _ = scripted([RetryCrash("after_ledger_credit")])
    with pytest.raises(RetryCrash):
        w.run(ScriptedStop(cycles=5))


@pytest.mark.parametrize("bad", [{"batch_size": 0}, {"lease_seconds": 0}, {"backoff_base": 0}])
def test_retry_config_refuses_nonsense(bad):
    with pytest.raises(ValueError):
        RetryConfig(worker_id="w", **bad)
