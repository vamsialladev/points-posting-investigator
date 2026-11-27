"""Alert rules as data, evaluated by deterministic code (RFC-0002 Phase 2; the minimal version of OBS-05).

A rule fires when all its conditions hold for one snapshot of signals. Rules come from `ops/alert-rules.yaml`; the
loader refuses anything it doesn't understand, so a typo can't silently disable a rule. A rule whose signal is
missing from the snapshot is reported as not evaluated, never as "not firing" (standing rule 7).
"""

from __future__ import annotations

import operator
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

RULES_FILE = Path(__file__).resolve().parent.parent.parent / "ops" / "alert-rules.yaml"
SIGNALS = frozenset(
    {
        "posted_in_window",
        "posted_in_previous_window",
        "dead_lettered_in_window",
        "consumer_lag",
        "parked_open",
        "parked_oldest_age_seconds",
        "outbox_unpublished",
        "outbox_oldest_age_seconds",
    }
)
OPS: dict[str, Callable[[float, float], bool]] = {
    ">=": operator.ge,
    ">": operator.gt,
    "<=": operator.le,
    "<": operator.lt,
    "==": operator.eq,
}


@dataclass(frozen=True)
class Condition:
    signal: str
    op: str
    value: float

    def holds(self, snapshot: Mapping[str, float]) -> bool:
        return OPS[self.op](snapshot[self.signal], self.value)


@dataclass(frozen=True)
class Rule:
    name: str
    owner: str
    summary: str
    when: tuple[Condition, ...]


@dataclass(frozen=True)
class Evaluation:
    """One rule against one snapshot. `state`: firing, quiet, or not_evaluated (a signal was missing)."""

    rule: str
    state: str
    values: tuple[tuple[str, float], ...] = ()  # the signals the rule read, for the stored evaluation
    missing: tuple[str, ...] = ()


def _keys(node: Any, allowed: set[str], where: str) -> dict[str, Any]:
    if not isinstance(node, dict) or set(node) != allowed:
        raise ValueError(f"{where}: expected exactly the keys {sorted(allowed)}")
    return node


def parse(document: Any) -> tuple[Rule, ...]:
    top = _keys(document, {"version", "rules"}, "alert rules")
    if top["version"] != 1 or not isinstance(top["rules"], list) or not top["rules"]:
        raise ValueError("alert rules: version must be 1 and at least one rule is required")
    rules = []
    for item in top["rules"]:
        raw = _keys(item, {"name", "owner", "summary", "when"}, "a rule")
        name = raw["name"]
        if not all(isinstance(raw[key], str) and raw[key].strip() for key in ("name", "owner", "summary")):
            raise ValueError(f"rule {name!r}: name, owner and summary are required text")
        if not isinstance(raw["when"], list) or not raw["when"]:
            raise ValueError(f"rule {name!r}: at least one condition is required")
        conditions = []
        for entry in raw["when"]:
            cond = _keys(entry, {"signal", "op", "value"}, f"rule {name!r}, a condition")
            if cond["signal"] not in SIGNALS:
                raise ValueError(f"rule {name!r}: unknown signal {cond['signal']!r}")
            if cond["op"] not in OPS:
                raise ValueError(f"rule {name!r}: unknown operator {cond['op']!r}")
            if isinstance(cond["value"], bool) or not isinstance(cond["value"], int | float):
                raise ValueError(f"rule {name!r}: the value must be a number")
            conditions.append(Condition(cond["signal"], cond["op"], float(cond["value"])))
        rules.append(Rule(name, raw["owner"], raw["summary"], tuple(conditions)))
    names = [rule.name for rule in rules]
    if len(set(names)) != len(names):
        raise ValueError("alert rules: rule names must be unique")
    return tuple(rules)


def load(path: Path = RULES_FILE) -> tuple[Rule, ...]:
    return parse(yaml.safe_load(path.read_text(encoding="utf-8")))


def evaluate(rules: tuple[Rule, ...], snapshot: Mapping[str, float]) -> list[Evaluation]:
    out = []
    for rule in rules:
        needed = tuple(dict.fromkeys(condition.signal for condition in rule.when))
        missing = tuple(signal for signal in needed if signal not in snapshot)
        if missing:
            out.append(Evaluation(rule.name, "not_evaluated", missing=missing))
            continue
        firing = all(condition.holds(snapshot) for condition in rule.when)
        values = tuple((signal, float(snapshot[signal])) for signal in needed)
        out.append(Evaluation(rule.name, "firing" if firing else "quiet", values))
    return out


def firing(evaluations: list[Evaluation]) -> list[str]:
    return [evaluation.rule for evaluation in evaluations if evaluation.state == "firing"]
