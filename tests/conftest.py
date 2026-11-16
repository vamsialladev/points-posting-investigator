"""Shared pytest setup. The REQUIRE_MARKERS guard lives in tests/required_markers.py (standing rule 7)."""

from tests.required_markers import (  # noqa: F401 (pytest finds hooks by name)
    pytest_collection_finish,
    pytest_runtest_makereport,
    pytest_sessionfinish,
)
