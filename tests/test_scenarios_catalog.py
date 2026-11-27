"""`app/scenarios/catalog.py` says exactly what the pre-registered `docs/failure-catalog.md` says (FAIL-00).

The document is the source. If they ever differ, the code is wrong (or the document needs a visible, locked change).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.ledger.api import MAX_POINTS
from app.scenarios import catalog, plans

ROOT = Path(__file__).resolve().parent.parent
DOC = (ROOT / "docs" / "failure-catalog.md").read_text(encoding="utf-8")


def doc_codes(heading: str) -> set[str]:
    section = DOC.split(f"## {heading}", 1)[1].split("\n## ", 1)[0]
    return set(re.findall(r"^\| `(\w+)` \|", section, re.MULTILINE))


def doc_scenarios() -> dict[str, tuple[str, str]]:
    parts = re.split(r"^### (S\d\d): (.*)$", DOC, flags=re.MULTILINE)
    return {parts[i]: (parts[i + 1], parts[i + 2].split("\n## ", 1)[0]) for i in range(1, len(parts), 3)}


def field(body: str, name: str) -> str:
    match = re.search(rf"\*\*{name}:\*\*(.*?)(?:\n- \*\*|\Z)", body, re.DOTALL)
    assert match, name
    return match.group(1)


def test_the_code_lists_equal_the_documents():
    assert doc_codes("Root-cause codes (closed list)") == catalog.ROOT_CAUSES
    assert doc_codes("Recovery codes (closed list)") == catalog.RECOVERIES


def test_every_scenario_has_the_documents_name_ground_truth_and_prediction():
    documented = doc_scenarios()
    assert list(documented) == list(catalog.SCENARIOS) and len(documented) == 18
    for scenario_id, (name, body) in documented.items():
        scenario = catalog.SCENARIOS[scenario_id]
        assert scenario.name == name
        assert scenario.rules_enough == (field(body, "Rules enough").strip().split(".")[0] == "yes"), scenario_id
        if scenario_id == "S15":
            continue
        assert re.findall(r"`(\w+)`", field(body, "Root cause")) == list(scenario.root_causes), scenario_id
        assert re.findall(r"`(\w+)`", field(body, "Recovery"))[0] == scenario.recovery, scenario_id


def test_the_compound_pairs_equal_the_documents():
    body = doc_scenarios()["S15"][1]
    for letter, pair in catalog.S15_PAIRS.items():
        parts = re.search(rf"\*\*Pair {letter}:\*\* (S\d\d) with (S\d\d)", body)
        assert parts and parts.groups() == pair.parts
        causes = re.search(rf"pair {letter} `(\w+)` and\s+`(\w+)`", field(body, "Root cause"))
        assert causes and causes.groups() == pair.root_causes
        assert re.search(rf"pair {letter} `(\w+)`", field(body, "Recovery")).group(1) == pair.recovery  # type: ignore[union-attr]


def test_the_planted_texts_are_the_documents_exact_texts():
    planted = re.findall(r"^  \d\. [^`]*`([^`]+)`$", doc_scenarios()["S17"][1], re.MULTILINE)
    assert planted == [
        catalog.INJECTION_CORRELATION_ID,
        catalog.INJECTION_LOG_MESSAGE,
        catalog.INJECTION_RUNBOOK_LINE,
    ]


def test_ground_truth_refuses_what_it_does_not_know():
    assert catalog.ground_truth("S11") == (("correction_before_original",), "dlq_replay")
    assert catalog.ground_truth("S15", "B") == (("correction_before_original", "producer_schema_break"), "dlq_replay")
    for scenario_id, pair in (("S99", None), ("S15", None), ("S15", "C"), ("S05", "A")):
        with pytest.raises(ValueError):
            catalog.ground_truth(scenario_id, pair)


def test_the_poison_limit_is_the_ledgers_limit():
    assert plans.LEDGER_MAX_POINTS == MAX_POINTS
