"""Write or check `benchmarks/preregistration.lock.json`: the SHA-256 of every pre-registered file (ADR-0019).

    uv run python scripts/prereg_lock.py --write     # after an allowed change, before committing it
    uv run python scripts/prereg_lock.py             # check only; exit 1 on a difference

The lock makes any edit to a pre-registered file a visible commit. `tests/test_preregistration.py` checks the same
hashes, and that the lock was last committed before any code under app/arms/ or app/investigator/.
Line endings are normalised to LF before hashing, so Windows and Linux checkouts agree.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = "benchmarks/preregistration.lock.json"
PREREGISTERED = (
    "docs/failure-catalog.md",
    "docs/hypotheses.md",
    "docs/benchmark-protocol.md",
    "benchmarks/thresholds.yaml",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def current(root: Path = ROOT) -> dict[str, str]:
    return {name: digest(root / name) for name in PREREGISTERED}


def main(argv: list[str]) -> int:
    hashes = current()
    lock = ROOT / LOCK
    if "--write" in argv:
        lock.write_text(json.dumps({"sha256": hashes}, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {LOCK} ({len(hashes)} files)")
        return 0
    if not lock.is_file():
        print(f"{LOCK} is missing")
        return 1
    locked = json.loads(lock.read_text(encoding="utf-8"))["sha256"]
    changed = sorted(name for name in set(hashes) | set(locked) if hashes.get(name) != locked.get(name))
    for name in changed:
        print(f"differs from the lock: {name}")
    print("lock matches" if not changed else f"{len(changed)} file(s) differ")
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
