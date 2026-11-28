"""`docker-compose.yml` parses, and every service gets the settings its code reads. Offline.

Added after a broken line (a mangled backslash) reached CI: nothing offline had parsed the file (verification log,
M3 Phase 2). `docker compose config` is the full check and runs wherever the stack starts; this one needs no Docker.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from app.db.roles import PASSWORD_VARIABLES
from app.scenarios import plans, stack

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]


def env(service: str) -> dict[str, str]:
    return SERVICES[service].get("environment", {})


def test_the_file_parses_and_has_the_stack_services():
    assert {
        "db",
        "kafka",
        "schema-registry",
        "db-init",
        "kafka-init",
        "ledger",
        "posting",
        "retry-worker",
        "relay",
    } <= set(SERVICES)
    assert set(SERVICES) >= stack.STACK_SERVICES, "every service a scenario may touch exists"


def test_db_init_gets_every_runtime_role_password():
    assert set(PASSWORD_VARIABLES) <= set(env("db-init"))


def test_every_service_that_logs_gets_the_ops_password_and_no_setting_spans_two_lines():
    for service in ("ledger", "posting", "retry-worker", "relay"):
        assert "OPS_DB_PASSWORD" in env(service), service
    for service, definition in SERVICES.items():
        for name, value in definition.get("environment", {}).items():
            assert "\n" not in str(value), f"{service}.{name} contains a line break"
            if ":?" in str(value):
                assert str(value).endswith("}"), f"{service}.{name}: the required-setting message is cut off"


def test_the_scenario_overridable_setting_reaches_the_two_services_that_read_it():
    for service in ("posting", "retry-worker"):
        assert (
            env(service)[plans.LEDGER_TIMEOUT_SETTING]
            == "${LEDGER_TIMEOUT_SECONDS:-" + plans.LEDGER_TIMEOUT_DEFAULT + "}"
        )
    assert {plans.LEDGER_TIMEOUT_SETTING} == set(stack.OVERRIDABLE)


def test_every_port_binds_to_loopback_only():
    for service, definition in SERVICES.items():
        for port in definition.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{service} publishes {port} beyond this machine"


def test_every_workflow_parses_pins_its_actions_and_asks_for_read_only_rights():
    import re

    workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    assert {path.name for path in workflows} >= {"ci.yml", "scenario-batch.yml"}
    for path in workflows:
        text = path.read_text(encoding="utf-8")
        document = yaml.safe_load(text)
        assert document["permissions"] == {"contents": "read"}, path.name
        uses = re.findall(r"uses: (\S+)", text)
        assert uses, path.name
        for action in uses:
            assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", action), f"{path.name}: {action} is not pinned to a commit"
        for job in document["jobs"].values():
            assert job["timeout-minutes"] <= 45, path.name


def test_the_batch_workflow_gives_the_stack_every_value_the_required_job_gives_it():
    """The two jobs start the same stack, so they must generate the same throwaway settings."""

    def generated(name: str) -> set[str]:
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        lines = [line for line in text.splitlines() if line.strip().startswith("for name in ")]
        assert lines, name
        return {frozenset(line.split(" in ", 1)[1].split(";")[0].split()) for line in lines}

    assert generated("scenario-batch.yml") <= generated("ci.yml")
    assert set(PASSWORD_VARIABLES) <= next(iter(generated("scenario-batch.yml")))
