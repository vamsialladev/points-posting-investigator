"""The pre-registration comes first, and stays as committed (standing rule 3, FAIL-00, BENCH-07, ADR-0019).

- The catalog, hypotheses, protocol and thresholds are committed, and their hashes are in the lock file.
- The lock file's last commit is before the first commit that touches `app/arms/` or `app/investigator/`.
- The thresholds in the YAML equal the table in the document.
- A shallow clone can't answer the order question, so it fails (rule 7: a check that tests nothing must fail).

The order logic runs against throwaway repositories too, so it is known to fail when it should.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
LOCK = "benchmarks/preregistration.lock.json"
PREREGISTERED = (
    "docs/failure-catalog.md",
    "docs/hypotheses.md",
    "docs/benchmark-protocol.md",
    "benchmarks/thresholds.yaml",
)
CODE_PATHS = ("app/arms", "app/investigator")
FIELDS = (
    "**Trigger:**",
    "**Expected behaviour:**",
    "**Root cause:**",
    "**Evidence:**",
    "**Recovery:**",
    "**Affected members:**",
    "**Reset:**",
    "**Rules enough:**",
)


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    assert done.returncode == 0, f"git {' '.join(args)}: {done.stderr.strip()}"
    return done.stdout.strip()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def lock_problems(repo: Path) -> list[str]:
    """Differences between the lock file and the files it names."""
    lock = repo / LOCK
    if not lock.is_file():
        return [f"{LOCK} is missing"]
    locked = json.loads(lock.read_text(encoding="utf-8"))["sha256"]
    problems = [f"{name} is not in the lock" for name in PREREGISTERED if name not in locked]
    problems += [f"the lock names {name}, which is not pre-registered" for name in locked if name not in PREREGISTERED]
    for name in PREREGISTERED:
        if not (repo / name).is_file():
            problems.append(f"{name} is missing")
        elif name in locked and digest(repo / name) != locked[name]:
            problems.append(f"{name} differs from the lock (scripts/prereg_lock.py --write, in its own commit)")
    return problems


def order_problems(repo: Path) -> list[str]:
    """Why the git history does not show the pre-registration coming first. Empty means it does."""
    if git(repo, "rev-parse", "--is-shallow-repository") == "true":
        return ["shallow clone: the history needed to check the order is missing (fetch-depth: 0)"]
    problems = []
    last = {}
    for name in (LOCK, *PREREGISTERED):
        last[name] = git(repo, "log", "-1", "--format=%H", "--", name)
        if not last[name]:
            problems.append(f"{name} is not committed")
    code = git(repo, "log", "--reverse", "--format=%H", "--", *CODE_PATHS).splitlines()
    if not code or problems:
        return problems
    first_code = code[0]
    for name, commit in last.items():
        before = subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", commit, first_code],
            capture_output=True,
            check=False,
        )
        if commit == first_code or before.returncode != 0:
            problems.append(
                f"{name} was last committed in {commit[:7]}, not before the first arm code {first_code[:7]}"
            )
    return problems


def flatten(node: object, prefix: str = "") -> dict[str, object]:
    if not isinstance(node, dict):
        return {prefix: node}
    out: dict[str, object] = {}
    for key, value in node.items():
        out.update(flatten(value, f"{prefix}.{key}" if prefix else str(key)))
    return out


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def scenarios() -> dict[str, str]:
    parts = re.split(r"^### (S\d\d): .*$", read("docs/failure-catalog.md"), flags=re.MULTILINE)
    return {parts[i]: parts[i + 1].split("\n## ", 1)[0] for i in range(1, len(parts), 2)}


def codes(heading: str) -> set[str]:
    section = read("docs/failure-catalog.md").split(f"## {heading}", 1)[1].split("\n## ", 1)[0]
    return set(re.findall(r"^\| `(\w+)` \|", section, re.MULTILINE))


# --- this repository ---------------------------------------------------------------------------------------------


def test_the_lock_matches_every_preregistered_file():
    assert lock_problems(ROOT) == []


def test_preregistration_is_committed_before_any_arm_or_investigator_code():
    assert order_problems(ROOT) == []


def test_thresholds_yaml_equals_the_table_in_the_hypotheses():
    from_yaml = flatten(yaml.safe_load(read("benchmarks/thresholds.yaml")))
    table = read("docs/hypotheses.md").split("## Thresholds", 1)[1].split("\n## ", 1)[0]
    from_doc = {key: yaml.safe_load(value) for key, value in re.findall(r"^\| `([\w.]+)` \| (\S+) \|$", table, re.M)}
    assert len(from_yaml) >= 15, "the YAML holds the thresholds"
    assert from_doc == from_yaml


def test_hypotheses_h1_to_h5_and_the_three_verdicts_are_registered():
    text = read("docs/hypotheses.md")
    assert re.findall(r"^## (H\d):", text, re.MULTILINE) == ["H1", "H2", "H3", "H4", "H5"]
    for verdict in ("**SUPPORTED:**", "**NOT SUPPORTED:**", "**NOT TESTED:**"):
        assert verdict in text, verdict


def test_the_catalog_has_all_18_scenarios_with_every_field():
    found = scenarios()
    assert list(found) == [f"S{n:02d}" for n in range(1, 19)]
    for scenario, body in found.items():
        for field in FIELDS:
            assert field in body, f"{scenario} lacks {field}"


def test_every_scenario_uses_only_the_closed_code_lists():
    root_causes, recoveries = codes("Root-cause codes (closed list)"), codes("Recovery codes (closed list)")
    assert len(root_causes) == 16 and recoveries == {"none", "dlq_replay", "outbox_rerun", "consumer_pause_resume"}
    used = set()
    for scenario, body in scenarios().items():
        root = re.search(r"\*\*Root cause:\*\*(.*?)\n- \*\*", body, re.DOTALL)
        recovery = re.search(r"\*\*Recovery:\*\*(.*?)\n- \*\*", body, re.DOTALL)
        assert root and recovery, scenario
        named = set(re.findall(r"`(\w+)`", root.group(1)))
        assert named and named <= root_causes, f"{scenario}: {named - root_causes}"
        assert len(named) == (4 if scenario == "S15" else 1), f"{scenario} names {sorted(named)}"
        recovered = set(re.findall(r"`(\w+)`", recovery.group(1)))
        assert recovered and recovered <= recoveries, f"{scenario}: {recovered - recoveries}"
        used |= named
    assert used == root_causes, f"codes no scenario uses: {root_causes - used}"


def test_the_rules_enough_list_agrees_with_each_entry():
    text = read("docs/failure-catalog.md")
    summary = text.split("## Scenarios where the rules baseline is expected to be enough", 1)[1].split("\n## ", 1)[0]
    enough, more = (set(re.findall(r"S\d\d", paragraph)) for paragraph in summary.split("Expected to need more", 1))
    per_entry = {s: re.search(r"\*\*Rules enough:\*\* (yes|no)", body) for s, body in scenarios().items()}
    assert all(per_entry.values())
    assert enough == {s for s, m in per_entry.items() if m and m.group(1) == "yes"}
    assert more == {s for s, m in per_entry.items() if m and m.group(1) == "no"}
    assert (
        set(re.findall(r"S\d\d", read("docs/hypotheses.md").split("Where the rules alone are enough", 1)[1])) >= enough
    )


def test_the_protocol_names_the_decision_split_and_forbids_tuning_on_it():
    text = " ".join(read("docs/benchmark-protocol.md").split())
    for phrase in (
        "Held-out is the decision split",
        "No tuning on held-out",
        "At least 60 incidents",
        "never shown as a model's result",
        "NOT RUN",
        "count and denominator",
    ):
        assert phrase in text, phrase


# --- the order check can fail (throwaway repositories) ------------------------------------------------------------


def commit(repo: Path, message: str, **files: str) -> None:
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", message)


def preregistration(note: str = "") -> dict[str, str]:
    files = {name: f"{name} {note}\n" for name in PREREGISTERED}
    hashes = {name: hashlib.sha256(content.encode()).hexdigest() for name, content in files.items()}
    return {**files, LOCK: json.dumps({"sha256": hashes})}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, "start", **{"README.md": "x\n"})
    return tmp_path


def test_order_passes_when_preregistration_precedes_the_code(repo):
    commit(repo, "prereg", **preregistration())
    assert order_problems(repo) == [] and lock_problems(repo) == []
    commit(repo, "investigator", **{"app/investigator/__init__.py": "\n"})
    assert order_problems(repo) == []


def test_order_fails_when_nothing_is_preregistered(repo):
    problems = order_problems(repo)
    assert len(problems) == 5 and all("is not committed" in p for p in problems)
    assert lock_problems(repo) == [f"{LOCK} is missing"]


def test_order_fails_when_the_code_came_first(repo):
    commit(repo, "arm first", **{"app/arms/rules.py": "\n"})
    commit(repo, "prereg afterwards", **preregistration())
    assert len(order_problems(repo)) == 5


def test_order_fails_when_code_and_preregistration_share_a_commit(repo):
    commit(repo, "both at once", **preregistration(), **{"app/investigator/loop.py": "\n"})
    assert len(order_problems(repo)) == 5


def test_order_fails_when_a_preregistered_file_changes_after_the_code(repo):
    commit(repo, "prereg", **preregistration())
    commit(repo, "investigator", **{"app/investigator/__init__.py": "\n"})
    commit(repo, "quiet edit", **preregistration("lower the bar"))
    problems = order_problems(repo)
    assert len(problems) == 5 and "not before the first arm code" in problems[0]


def test_an_edit_without_a_new_lock_is_caught(repo):
    commit(repo, "prereg", **preregistration())
    (repo / "benchmarks/thresholds.yaml").write_text("min: 0\n", encoding="utf-8")
    assert lock_problems(repo) == [
        "benchmarks/thresholds.yaml differs from the lock (scripts/prereg_lock.py --write, in its own commit)"
    ]


def test_a_shallow_clone_fails_instead_of_passing(repo, tmp_path_factory):
    commit(repo, "prereg", **preregistration())
    commit(repo, "more", **{"README.md": "y\n"})
    shallow = tmp_path_factory.mktemp("shallow")
    git(shallow, "clone", "-q", "--depth", "1", repo.as_uri(), "clone")
    assert order_problems(shallow / "clone") == [
        "shallow clone: the history needed to check the order is missing (fetch-depth: 0)"
    ]
