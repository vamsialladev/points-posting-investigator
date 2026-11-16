"""A check that tests nothing must fail (standing rule 7; Stage 9's REQUIRE_BROWSER guard, generalised).

Set REQUIRE_MARKERS to a comma-separated list of markers (for example "postgres,kafka"). Then, for each of them:
- a test with that marker that skips (no database, no broker, no browser) is reported as a failure, and
- if no test with that marker was selected at all, the session fails.

CI and scripts\\ci_local.ps1 set it for the jobs that start real services, so "all green" can never mean
"everything skipped". Without REQUIRE_MARKERS, skips stay skips (a laptop without Docker running).
"""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest

_SELECTED = pytest.StashKey[dict[str, int]]()


def required_markers() -> set[str]:
    return {name.strip() for name in os.environ.get("REQUIRE_MARKERS", "").split(",") if name.strip()}


def pytest_collection_finish(session: pytest.Session) -> None:
    # After `-m` / `-k` deselection (pytest_collection_modifyitems would count tests that are then deselected:
    # tests/test_required_markers.py::test_deselecting_every_required_test_fails_too caught that).
    counts = {name: 0 for name in required_markers()}
    for item in session.items:
        for name in counts:
            if item.get_closest_marker(name) is not None:
                counts[name] += 1
    session.config.stash[_SELECTED] = counts


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    required = [name for name in required_markers() if item.get_closest_marker(name) is not None]
    if report.skipped and required:
        reason = report.longrepr[2] if isinstance(report.longrepr, tuple) else str(report.longrepr)
        report.outcome = "failed"
        report.longrepr = (
            f"REQUIRE_MARKERS={','.join(sorted(required))}: this test must run here, but it skipped: {reason}"
        )
    return report


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    counts = session.config.stash.get(_SELECTED, {})
    empty = sorted(name for name, count in counts.items() if count == 0)
    if empty:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        message = f"REQUIRE_MARKERS: no test with marker(s) {', '.join(empty)} was selected, so nothing was tested"
        if reporter is not None:
            reporter.write_line(message, red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
