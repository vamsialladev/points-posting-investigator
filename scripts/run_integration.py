"""Run the real-Postgres and real-Kafka tests against the local stack (scripts\\test_integration.ps1 calls this).

It reads `.env` with python-dotenv inside this process, passes the stack's addresses to pytest as TEST_* variables,
and sets REQUIRE_MARKERS=postgres,kafka so a skipped or missing test fails (standing rule 7). No value is printed:
only which names were found.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
MAPPING = {
    "TEST_DATABASE_URL": "DATABASE_URL",
    "TEST_KAFKA_BOOTSTRAP_SERVERS": "KAFKA_BOOTSTRAP_SERVERS",
    "TEST_SCHEMA_REGISTRY_URL": "SCHEMA_REGISTRY_URL",
    "TEST_LEDGER_URL": "LEDGER_API_URL",
    "TEST_LEDGER_TOKEN": "LEDGER_API_TOKEN",
    "TEST_POSTING_DB_PASSWORD": "POSTING_DB_PASSWORD",
}
FIXED = {"TEST_RELAY_METRICS_URL": "http://127.0.0.1:9108/metrics"}  # the compose relay's port, not a secret


def main(argv: list[str]) -> int:
    values = dotenv_values(ROOT / ".env")  # interpolates ${POSTGRES_PASSWORD} inside DATABASE_URL
    env = dict(os.environ)
    missing = []
    for target, source in MAPPING.items():
        value = env.get(target) or values.get(source)
        if value:
            env[target] = value
        else:
            missing.append(source)
    found = len(MAPPING) - len(missing)
    print(f"stack settings: {found}/{len(MAPPING)} set" + (f"; missing {missing}" if missing else ""))
    for name, value in FIXED.items():
        env.setdefault(name, value)
    env["REQUIRE_MARKERS"] = "postgres,kafka"
    # `--batch` runs only the slow scenario batch (tests/test_scenarios_batch.py); without it the batch is left out,
    # so the required CI job stays fast. Either way a skipped or missing postgres/kafka test is a failure.
    batch = "--batch" in argv
    argv = [arg for arg in argv if arg != "--batch"]
    selection = "batch" if batch else "(postgres or kafka) and not batch"
    command = [sys.executable, "-m", "pytest", "-m", selection, "-rs", "-p", "no:cacheprovider", *argv]
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode  # noqa: S603 (fixed command)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
