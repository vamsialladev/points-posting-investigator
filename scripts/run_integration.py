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
}


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
    env["REQUIRE_MARKERS"] = "postgres,kafka"
    command = [sys.executable, "-m", "pytest", "-m", "postgres or kafka", "-rs", "-p", "no:cacheprovider", *argv]
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode  # noqa: S603 (fixed command)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
