"""The committed Avro schemas, one file per topic and version under `schemas/` (RFC-0001 D4).

Subjects follow the registry's default TopicNameStrategy: `<topic>-value`. Compatibility is BACKWARD_TRANSITIVE: a
new version must read every older version's data.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_DIR = ROOT / "schemas"
COMPATIBILITY = "BACKWARD_TRANSITIVE"
_FILE = re.compile(r"(?P<topic>[a-z_.]+)\.v(?P<version>\d+)\.avsc")


def subject(topic: str) -> str:
    return f"{topic}-value"


def versions(topic: str) -> list[tuple[int, str]]:
    """Every committed version of a topic's schema, oldest first, as (version, schema JSON text)."""
    found = []
    for path in SCHEMA_DIR.glob("*.avsc"):
        match = _FILE.fullmatch(path.name)
        if match and match["topic"] == topic:
            text = path.read_text(encoding="utf-8")
            json.loads(text)  # a broken file fails here, not at publish time
            found.append((int(match["version"]), text))
    return sorted(found)


def latest(topic: str) -> str:
    found = versions(topic)
    if not found:
        raise FileNotFoundError(f"no schema committed for {topic} in {SCHEMA_DIR}")
    return found[-1][1]
