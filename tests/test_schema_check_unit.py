"""The schema gate's local check, offline (DEL-07). The registry side: tests/test_kafka_stack.py."""

from __future__ import annotations

import copy
import json

import pytest

from app.pipeline import schemas, topics
from app.pipeline.schema_check import backward_problems, check_committed, check_registry, main

V1 = json.loads(schemas.latest(topics.CHECKED_OUT))


def changed(**edits):
    schema = copy.deepcopy(V1)
    for name, field in edits.items():
        if field is None:
            schema["fields"] = [f for f in schema["fields"] if f["name"] != name]
        elif any(f["name"] == name for f in schema["fields"]):
            schema["fields"] = [field if f["name"] == name else f for f in schema["fields"]]
        else:
            schema["fields"].append(field)
    return schema


def test_the_committed_schemas_pass():
    checked, problems = check_committed()
    assert problems == [] and checked >= 2  # stay.checked_out and points.posted, every version


@pytest.mark.parametrize(
    ("new", "ok"),
    [
        (changed(loyalty_note={"name": "loyalty_note", "type": ["null", "string"], "default": None}), True),
        (changed(fees_cents=None), True),  # dropping a field: old data still reads
        (changed(nights={"name": "nights", "type": "long"}), True),  # int -> long is an Avro promotion
        (changed(loyalty_note={"name": "loyalty_note", "type": "string"}), False),  # new field, no default
        (changed(nights={"name": "nights", "type": "string"}), False),  # int -> string
        (changed(room_rate_cents={"name": "room_rate_cents", "type": "int"}), False),  # long -> int narrows
        (changed(check_in={"name": "check_in", "type": "int"}), False),  # a logical type dropped
    ],
)
def test_backward_compatibility_rules(new, ok):
    assert (backward_problems(V1, new) == []) is ok


def test_a_renamed_record_is_a_problem():
    assert backward_problems(V1, {**V1, "name": "Other"}) != []


def test_a_breaking_version_is_caught_against_every_older_one():
    v2 = changed(loyalty_note={"name": "loyalty_note", "type": ["null", "string"], "default": None})
    v3 = changed(fees_cents=None, loyalty_note={"name": "loyalty_note", "type": "string"})  # no default
    chain = {"t": [(1, json.dumps(V1)), (2, json.dumps(v2)), (3, json.dumps(v3))]}
    checked, problems = check_committed(chain)
    assert checked == 3
    assert [p.split(":")[0] for p in problems] == ["t v3 vs v1", "t v3 vs v2"]


def test_a_gate_with_nothing_to_check_fails():
    assert check_committed({})[1] == ["no schema was checked"]
    assert "t: no committed schema" in check_committed({"t": []})[1]


class FakeRegistry:
    def __init__(self, refuse_version=None):
        self.refuse_version, self.registered, self.configs = refuse_version, [], {}

    def set_config(self, subject, config):
        self.configs[subject] = config.compatibility.value

    def register_schema(self, subject, schema):
        from confluent_kafka.schema_registry.error import SchemaRegistryError

        version = len([s for s, _ in self.registered if s == subject]) + 1
        if version == self.refuse_version:
            raise SchemaRegistryError(409, 409, "incompatible")
        self.registered.append((subject, schema.schema_str))
        return version


def test_the_registry_check_registers_in_order_and_reports_a_refusal():
    chain = {"t": [(1, json.dumps(V1)), (2, json.dumps(V1))]}
    ok = FakeRegistry()
    assert check_registry(ok, chain) == [] and len(ok.registered) == 2
    assert ok.configs == {"t-value": "BACKWARD_TRANSITIVE"}
    refused = FakeRegistry(refuse_version=2)
    assert check_registry(refused, chain) == ["t-value v2: the registry refused it (409)"]


def test_the_command_passes_on_the_committed_schemas(capsys):
    assert main([]) == 0
    assert "schema gate: passed" in capsys.readouterr().out
