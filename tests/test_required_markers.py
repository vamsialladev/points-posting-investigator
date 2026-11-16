"""REQUIRE_MARKERS turns skipped infrastructure tests, and missing ones, into failures (standing rule 7)."""

import pytest

CONFTEST = (
    "from tests.required_markers import pytest_collection_finish, pytest_runtest_makereport, pytest_sessionfinish\n"
)

SKIPPING_POSTGRES_TEST = """
import pytest

@pytest.mark.postgres
def test_needs_a_database():
    pytest.skip("TEST_DATABASE_URL is not set")

def test_plain():
    assert True
"""


@pytest.fixture
def suite(pytester: pytest.Pytester) -> pytest.Pytester:
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile(test_suite=SKIPPING_POSTGRES_TEST)
    return pytester


def test_without_the_setting_a_skip_stays_a_skip(suite, monkeypatch):
    monkeypatch.delenv("REQUIRE_MARKERS", raising=False)
    result = suite.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(passed=1, skipped=1)
    assert result.ret == 0


def test_a_required_marker_that_skips_is_a_failure(suite, monkeypatch):
    monkeypatch.setenv("REQUIRE_MARKERS", "postgres")
    result = suite.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(passed=1, failed=1)
    result.stdout.fnmatch_lines(["*must run here, but it skipped*TEST_DATABASE_URL is not set*"])
    assert result.ret == pytest.ExitCode.TESTS_FAILED


def test_a_required_marker_with_no_tests_fails_the_session(suite, monkeypatch):
    monkeypatch.setenv("REQUIRE_MARKERS", "kafka")
    result = suite.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(passed=1, skipped=1)
    result.stdout.fnmatch_lines(["*no test with marker(s) kafka was selected*"])
    assert result.ret == pytest.ExitCode.TESTS_FAILED


def test_deselecting_every_required_test_fails_too(suite, monkeypatch):
    # `-m "not postgres"` with REQUIRE_MARKERS=postgres would otherwise be green while testing nothing that matters.
    monkeypatch.setenv("REQUIRE_MARKERS", "postgres")
    result = suite.runpytest("-p", "no:cacheprovider", "-m", "not postgres")
    assert result.ret == pytest.ExitCode.TESTS_FAILED
