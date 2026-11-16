"""Find `.env` secret values inside Git-tracked files. Reports file and variable names, never values.

    python -m app.env_leaks

Exit codes: 0 = checked and clean, 1 = a leak was found, 3 = NOT RUN (nothing was checked).

Ported from Stage 9's `app/env_leaks.py`, with one change (standing rule 7, ADR-0007): Stage 9's version exits 0
when there is no `.env`, so it "passes" having scanned nothing. Here a check that scans nothing fails: no `.env`,
no secret values in it, or no tracked files all report NOT RUN with exit code 3.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

from dotenv import dotenv_values

from app.preflight import SECRET_NAMES

SECRET_LIKE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)$")
MIN_LENGTH = 8
NOT_RUN = 3


def secret_values(values: Mapping[str, str | None], template: Mapping[str, str | None] | None = None) -> dict[str, str]:
    """Values worth searching for: secret-flagged or secret-looking names, at least MIN_LENGTH characters.

    A value equal to the template's own value (an unchanged default from .env.example) is not a secret.
    """
    template = template or {}
    return {
        name: value
        for name, value in values.items()
        if value
        and len(value.strip()) >= MIN_LENGTH
        and (name in SECRET_NAMES or SECRET_LIKE.search(name))
        and value != template.get(name)
    }


def find_leaks(secrets: Mapping[str, str], files: Iterable[Path]) -> list[tuple[str, str]]:
    """(file, variable name) for every secret value found in a file. Binary files are searched as bytes."""
    needles = {name: value.strip().encode() for name, value in secrets.items()}
    leaks: list[tuple[str, str]] = []
    for path in files:
        try:
            data = path.read_bytes()
        except OSError:
            continue
        leaks.extend((str(path), name) for name, needle in needles.items() if needle in data)
    return leaks


def tracked_files(repo: Path) -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=repo, capture_output=True, check=True).stdout
    return [repo / name for name in out.decode().split("\0") if name]


def main(repo: Path = Path(".")) -> int:
    env = repo / ".env"
    if not env.is_file():
        print("NOT RUN: no .env file, so no secret value was checked. Create .env first (see .env.example).")
        return NOT_RUN
    template = repo / ".env.example"
    secrets = secret_values(dotenv_values(env), dotenv_values(template) if template.is_file() else None)
    if not secrets:
        print("NOT RUN: .env holds no secret values to search for, so nothing was checked.")
        return NOT_RUN
    files = tracked_files(repo)
    if not files:
        print("NOT RUN: Git tracks no files here, so nothing was checked.")
        return NOT_RUN
    leaks = find_leaks(secrets, files)
    for path, name in leaks:
        print(f"LEAK: the value of {name} from .env appears in {path}")
    print(
        f"Checked {len(secrets)} secret value(s) from .env against {len(files)} tracked file(s): {len(leaks)} leak(s)."
    )
    return 1 if leaks else 0


if __name__ == "__main__":
    sys.exit(main())
