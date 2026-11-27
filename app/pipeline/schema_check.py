"""The schema gate: every committed schema version must read every older version's data (RFC-0001 D4, DEL-07).

    python -m app.pipeline.schema_check                       # local check of schemas/*.avsc (offline)
    python -m app.pipeline.schema_check --registry http://127.0.0.1:8081   # and the registry's verdict (CI)

Two layers:
1. **Local, structural** (`backward_problems`): for flat Avro records like ours, a new version may add a field only
   with a default, may drop a field, and may not change a field's type except by Avro's promotions (int -> long, etc.).
   Checked against EVERY older version (BACKWARD_TRANSITIVE). It's a fast pre-check, not the authority: it doesn't
   handle nested records, unions changing shape, or aliases.
2. **The registry** (`check_registry`): sets BACKWARD_TRANSITIVE on each subject and registers the committed versions
   in order. The registry refuses an incompatible one, and that fails the gate. In CI this runs against the job's own
   throwaway registry.

A gate that finds no schema fails: it would otherwise pass having checked nothing (standing rule 7).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from app.pipeline import schemas, topics

# Avro's allowed promotions (writer type -> reader types that can read it).
PROMOTIONS = {
    "int": {"int", "long", "float", "double"},
    "long": {"long", "float", "double"},
    "float": {"float", "double"},
    "string": {"string", "bytes"},
    "bytes": {"bytes", "string"},
}

GATED_TOPICS = (topics.CHECKED_OUT, topics.POINTS_POSTED)


def _type_name(field_type: Any) -> str:
    """A comparable name for a field's type: 'long', 'long/timestamp-millis', or the JSON of anything complex."""
    if isinstance(field_type, str):
        return field_type
    if (
        isinstance(field_type, dict)
        and isinstance(field_type.get("type"), str)
        and set(field_type)
        <= {
            "type",
            "logicalType",
        }
    ):
        logical = field_type.get("logicalType")
        return f"{field_type['type']}/{logical}" if logical else field_type["type"]
    return json.dumps(field_type, sort_keys=True)


def _readable(writer: str, reader: str) -> bool:
    if writer == reader:
        return True
    if "/" in writer or "/" in reader or writer.startswith(("[", "{")) or reader.startswith(("[", "{")):
        return False  # logical types and complex types must match exactly in this structural check
    return reader in PROMOTIONS.get(writer, {writer})


def backward_problems(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Why `new` (the reader) can't read data written with `old`; empty if it can."""
    if old.get("type") != "record" or new.get("type") != "record":
        return ["only records are checked"]
    problems = []
    if (old.get("namespace"), old.get("name")) != (new.get("namespace"), new.get("name")):
        problems.append("the record's name or namespace changed")
    written = {f["name"]: f for f in old["fields"]}
    for field in new["fields"]:
        name = field["name"]
        if name not in written:
            if "default" not in field:
                problems.append(f"new field {name!r} has no default, so old data can't be read")
            continue
        before, after = _type_name(written[name]["type"]), _type_name(field["type"])
        if not _readable(before, after):
            problems.append(f"field {name!r} changed type from {before} to {after}")
    return problems


def check_committed(versions: dict[str, list[tuple[int, str]]] | None = None) -> tuple[int, list[str]]:
    """(schemas checked, problems) for every committed topic, each version against every older one."""
    found = versions if versions is not None else {topic: schemas.versions(topic) for topic in GATED_TOPICS}
    checked, problems = 0, []
    for topic, chain in found.items():
        if not chain:
            problems.append(f"{topic}: no committed schema")
            continue
        parsed = [(number, json.loads(text)) for number, text in chain]
        checked += len(parsed)
        for i, (number, new) in enumerate(parsed):
            for older_number, old in parsed[:i]:
                problems += [f"{topic} v{number} vs v{older_number}: {p}" for p in backward_problems(old, new)]
    if checked == 0:
        problems.append("no schema was checked")
    return checked, problems


def check_registry(client: Any, versions: dict[str, list[tuple[int, str]]] | None = None) -> list[str]:
    """Register every committed version, oldest first, under BACKWARD_TRANSITIVE. Problems are refusals."""
    from confluent_kafka.schema_registry import ConfigCompatibilityLevel, Schema, ServerConfig
    from confluent_kafka.schema_registry.error import SchemaRegistryError

    found = versions if versions is not None else {topic: schemas.versions(topic) for topic in GATED_TOPICS}
    level = ConfigCompatibilityLevel(schemas.COMPATIBILITY)
    problems = []
    for topic, chain in found.items():
        subject = schemas.subject(topic)
        client.set_config(subject, ServerConfig(compatibility=level))
        for number, text in chain:
            try:
                client.register_schema(subject, Schema(text, "AVRO"))
            except SchemaRegistryError as exc:
                problems.append(f"{subject} v{number}: the registry refused it ({exc.http_status_code})")
                break
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check committed Avro schemas for BACKWARD_TRANSITIVE compatibility")
    parser.add_argument("--registry", help="also register them with this schema registry (CI: the throwaway one)")
    args = parser.parse_args(argv)
    checked, problems = check_committed()
    print(f"local: {checked} committed schema version(s) checked")
    if args.registry and not problems:
        from confluent_kafka.schema_registry import SchemaRegistryClient

        problems += check_registry(SchemaRegistryClient({"url": args.registry}))
        print(f"registry: {len(GATED_TOPICS)} subject(s) registered under {schemas.COMPATIBILITY}")
    for problem in problems:
        print(f"FAIL {problem}")
    print("schema gate: " + ("FAILED" if problems else "passed"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
