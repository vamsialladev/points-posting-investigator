"""Milestone 1 guidance and tracking files exist and say what they must (spec 0.3, Part A, Appendix A; rules 1-10)."""

import re
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NOREPLY = "339370878+vamsialladev@users.noreply.github.com"

TRACKING = [
    "implementation-plan.md",
    "implementation-status.md",
    "requirements-matrix.md",
    "decisions.md",
    "session-handoff.md",
    "verification-log.md",
    "known-limitations.md",
    "backlog.md",
]
MILESTONE_1_DOCS = [
    "continuity.md",
    "discovery.md",
    "workflow.md",
    "project-purpose.md",
    "role-coverage-map.md",
    "onboarding.md",
    "MASTER-SPEC.md",
]
STATUS = re.compile(
    r"^(Implemented and verified|Implemented but unverified|Simulated|Documentation-only|Manual step required"
    r"|Blocked \(.+\)|Deferred \(.+\)|Planned \(M\d+\)|Planned \(v2\))$"
)
DASH = "\u2013"  # the table's empty-cell mark
SPEC_PARTS = ["0", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P"]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def flat(text: str) -> str:
    return " ".join(text.split())


def matrix_rows() -> list[dict[str, str]]:
    rows = []
    header: list[str] = []
    for line in read("docs/requirements-matrix.md").splitlines():
        if not line.startswith("|"):
            header = [] if not line.strip() else header
            continue
        if re.fullmatch(r"\|[-| :]+\|", line.strip()):
            continue  # the separator row under a header
        cells = [cell.strip() for cell in line.strip().strip("|").split(" | ")]
        if cells[0] == "ID":
            header = cells
        elif header:
            assert len(cells) == len(header), f"malformed matrix row: {line[:80]}"
            rows.append(dict(zip(header, cells, strict=True)))
    return rows


@pytest.mark.parametrize("name", TRACKING + MILESTONE_1_DOCS)
def test_tracking_files_exist(name):
    path = ROOT / "docs" / name
    assert path.is_file(), f"docs/{name} is missing"
    assert len(path.read_text(encoding="utf-8").strip()) > 200, f"docs/{name} is nearly empty"


def test_claude_md_keeps_the_owners_standing_rules():
    text = read("CLAUDE.md")
    section = text.split("## Standing rules from the owner", 1)[1].split("\n## ", 1)[0]
    numbered = re.findall(r"^(\d+)\. ", section, re.MULTILINE)
    assert numbered == [str(n) for n in range(1, 11)], "the ten standing rules, in order"
    section = flat(section)
    for phrase in (
        "a v1 release first",
        "Plan before code on design-heavy milestones",
        "Every number traces to a stored result file",
        "Mock results are never presented as live",
        "Report where AI did not help",
        "Never put a secret in a command line or prompt text",
        "prove the old credential fails",
        "explicit OK and a stated cap",
        "Mock AI by default",
        "merge with a merge commit only when CI is green",
        "Ask before creating the GitHub repo",
        "Never weaken or delete a test to make it pass",
        "A check that scans or tests nothing must fail",
        "Purpose lenses",
        "role-coverage-map.md",
        "Website changes only as PRs the owner approves",
        "3-line summary",
        NOREPLY,
    ):
        assert phrase in section, phrase


def test_claude_md_scopes_the_repo_and_protects_stage_9():
    text = flat(read("CLAUDE.md"))
    assert "This folder is the repository root" in text
    assert "Stage 9 (`..\\loyalty-support-modernization`) is read-only" in text
    assert "do not apply here" in text


def test_design_heavy_milestones_agree_everywhere():
    assert "**2, 3, 6, 7, 9, 10**" in read("CLAUDE.md")
    assert "Milestones 2, 3, 6, 7, 9, 10" in read("AGENTS.md")
    plan = read("docs/implementation-plan.md")
    rows = re.findall(r"^\| (\d+) \|.*\| (\*\*yes\*\*|\u2013)[^|]*\|$", plan, re.MULTILINE)
    heavy = [milestone for milestone, flag in rows if flag != DASH]
    assert heavy == ["2", "3", "6", "7", "9"], heavy  # M10 is v2, listed in §2


def test_agents_md_points_to_claude_md():
    text = flat(read("AGENTS.md"))
    for phrase in ("CLAUDE.md", "docs/MASTER-SPEC.md", "AI is read-only", "optional exercise", NOREPLY):
        assert phrase in text, phrase
    assert "Never open or print `.env`" in text


def test_adrs_have_the_stage9_headings():
    text = read("docs/decisions.md")
    numbers = [int(n) for n in re.findall(r"^## ADR-(\d{4}):", text, re.MULTILINE)]
    assert numbers == list(range(1, len(numbers) + 1)), "ADRs are numbered in order without gaps"
    for block in text.split("\n## ADR-")[1:]:
        for heading in ("**Context:**", "**Options considered:**", "**Decision:**", "**Tradeoff:**", "**Result:**"):
            assert heading in block, f"ADR-{block[:4]} lacks {heading}"
        assert "**What would change this decision:**" in block, f"ADR-{block[:4]}"


def test_every_matrix_row_has_a_release_and_a_known_status():
    rows = matrix_rows()
    assert len(rows) > 100
    ids = [row["ID"] for row in rows]
    assert [i for i, n in Counter(ids).items() if n > 1] == [], "requirement IDs are unique"
    for row in rows:
        assert row["Release"] in ("v1", "v2"), row["ID"]
        assert STATUS.match(row["Status"]), f"{row['ID']}: unknown status {row['Status']!r}"
        if row["Release"] == "v2":
            assert row["Status"] == "Planned (v2)", f"{row['ID']} is v2 but has status {row['Status']}"
        else:
            assert row["Status"] != "Planned (v2)", f"{row['ID']} is v1 but marked Planned (v2)"
        if row["Status"] == "Implemented and verified":
            assert row["Evidence"] not in ("", DASH), f"{row['ID']} is verified without evidence"


def test_every_spec_part_has_matrix_rows():
    text = read("docs/requirements-matrix.md")
    for part in SPEC_PARTS:
        assert re.search(rf"^## Part {part}\b", text, re.MULTILINE), f"no section for spec Part {part}"
    spec = read("docs/MASTER-SPEC.md")
    for part in SPEC_PARTS[1:]:
        assert re.search(rf"^## PART {part}\b", spec, re.MULTILINE), f"spec has no Part {part}?"


def test_matrix_evidence_points_at_tests_that_exist():
    """A row can't cite a test that doesn't exist (rule 3: every claim traces to something real)."""
    missing = []
    for row in matrix_rows():
        for path, name in re.findall(r"tests/([\w/]+\.py)::(\w+)", row["Evidence"]):
            file = ROOT / "tests" / path
            if not file.is_file() or not re.search(rf"^def {name}\(", file.read_text(encoding="utf-8"), re.MULTILINE):
                missing.append(f"{row['ID']}: tests/{path}::{name}")
    assert missing == []


def test_matrix_implementation_paths_exist():
    missing = []
    for row in matrix_rows():
        if row["Status"] != "Implemented and verified":
            continue
        for path in re.findall(r"`((?:app|tests|scripts|docs)[/\\][\w./\\-]+\.(?:py|md|ps1))`", row["Implementation"]):
            if not (ROOT / path.replace("\\", "/")).is_file():
                missing.append(f"{row['ID']}: {path}")
    assert missing == []


def test_status_counts_match_the_matrix():
    rows = matrix_rows()
    table = read("docs/implementation-status.md").split("## Counts", 1)[1]
    for release in ("v1", "v2"):
        of_release = [row for row in rows if row["Release"] == release]
        expected = [
            len(of_release),
            sum(row["Status"] == "Implemented and verified" for row in of_release),
            sum(row["Status"] == "Manual step required" for row in of_release),
            sum(row["Status"].startswith("Planned") for row in of_release),
        ]
        line = re.search(rf"^\| {release} \| (\d+) \| (\d+) \| (\d+) \| (\d+) \|$", table, re.MULTILINE)
        assert line, f"no counts row for {release}"
        assert [int(n) for n in line.groups()] == expected, f"{release}: status table says {line.groups()}"


def test_python_312_and_java_in_backlog():
    assert 'requires-python = ">=3.12,<3.13"' in read("pyproject.toml")
    assert "Java / Spring Boot" in read("docs/backlog.md")


def test_discovery_covers_part_a():
    text = read("docs/discovery.md")
    assert "FICTIONAL" in text.split("\n", 1)[0] and "Everything in this document is fictional" in text
    for stakeholder in (
        "Integration / platform engineers",
        "On-call SRE",
        "Loyalty operations lead",
        "Support supervisor",
        "Security",
        "Engineering manager",
    ):
        assert stakeholder in text, stakeholder
    headings = ("Interview excerpts (FICTIONAL)", "hypotheses to measure", "Success metrics", "Scope", "Exclusions")
    for heading in headings:
        assert heading in text, heading
    assert "RACI" in text and "What stays deterministic and what the AI does" in text
    for metric in ("Time to diagnosis", "Root-cause accuracy", "Wrong recovery proposals", "Time to correct points"):
        assert metric in text


def test_workflow_has_current_and_proposed():
    text = read("docs/workflow.md")
    assert "FICTIONAL" in text.split("\n", 1)[0]
    assert "## 1. Current workflow" in text and "## 2. Proposed workflow" in text
    assert text.count("```mermaid") == 2 and text.count("```") == 4, "two closed Mermaid blocks"


def test_role_map_claims_nothing_without_evidence():
    rows = []
    for line in read("docs/role-coverage-map.md").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if line.startswith("|") and len(cells) == 5 and cells[0] not in ("Role",) and not set(cells[0]) <= set("-"):
            rows.append(cells)
    assert len(rows) == 17, "one row per role in lens 11"
    for role, evidence, _milestone, status, _questions in rows:
        if status.startswith("Shown"):
            paths = re.findall(r"`([\w./\\-]+\.(?:md|py|ps1|json|yaml))`", evidence)
            assert paths, f"{role} is Shown without evidence"
            for path in paths:
                assert (ROOT / path.replace("\\", "/")).is_file(), f"{role}: {path} doesn't exist"
        else:
            assert status.startswith("Planned"), f"{role}: {status}"


def test_handoff_ends_the_milestone_with_three_lines():
    text = read("docs/session-handoff.md")
    summary = text.split("## Milestone 1 in three lines", 1)[1].split("\n## ", 1)[0]
    lines = [line for line in summary.strip().splitlines() if line.strip()]
    assert len(lines) == 3, lines
