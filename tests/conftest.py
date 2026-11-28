"""Shared pytest setup. The REQUIRE_MARKERS guard lives in tests/required_markers.py (standing rule 7); the
real-infrastructure fixtures live in tests/infra.py."""

from tests.infra import admin, host, kafka, passwords, registry  # noqa: F401 (pytest finds fixtures by name)
from tests.pipeline_fixtures import db, ledger, scratch  # noqa: F401 (pytest finds fixtures by name)
from tests.required_markers import (  # noqa: F401 (pytest finds hooks by name)
    pytest_collection_finish,
    pytest_runtest_makereport,
    pytest_sessionfinish,
)
from tests.scenario_helpers import effects  # noqa: F401 (pytest finds fixtures by name)
