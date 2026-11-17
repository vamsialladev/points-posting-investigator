"""Secrets stay out of Git, images and Claude Code's reach (rule 4, spec 0.3 and Part I)."""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GITLEAKS = "ghcr.io/gitleaks/gitleaks:v8.30.1"
# The owner starts sessions in the parent folder, so its rules are the ones that apply there (ADR-0008).
PROJECT1_SETTINGS = ROOT.parent / ".claude" / "settings.json"
TEMPLATE = ".env.example"
ENV_NAME = re.compile(r"\.env(\..+)?|.+\.env")  # .env, .env.qa, .env.prod.bak, prod.env
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", [".env", ".env.local", ".env.bak", "secrets/x.txt", "deploy.pem", "id_ed25519"])
def test_git_ignores_secret_files(name):
    result = subprocess.run(["git", "check-ignore", "-q", "--no-index", name], cwd=ROOT, check=False)
    assert result.returncode == 0, f"{name} is not ignored by .gitignore"


def test_git_keeps_the_template():
    result = subprocess.run(["git", "check-ignore", "-q", "--no-index", ".env.example"], cwd=ROOT, check=False)
    assert result.returncode == 1, ".env.example must be committed"


def test_docker_images_never_get_env_files():
    lines = read(".dockerignore").splitlines()
    assert ".env" in lines and ".env.*" in lines


def test_claude_code_is_denied_env_files():
    deny = json.loads(read(".claude/settings.json"))["permissions"]["deny"]
    for rule in ("Read(./.env)", "Read(./**/.env)", "Edit(./.env)", "Write(./.env)", "Read(./secrets/**)"):
        assert rule in deny, rule
    assert any(rule.startswith("PowerShell(Get-Content") for rule in deny)


def test_claude_code_is_denied_any_file_ending_in_env():
    """ADR-0009: prod.env or deny-canary.env is as secret as .env, for Read, Edit and Write alike."""
    deny = json.loads(read(".claude/settings.json"))["permissions"]["deny"]
    for tool in ("Read", "Edit", "Write"):
        for pattern in ("./*.env", "./**/*.env"):
            assert f"{tool}({pattern})" in deny, f"{tool}({pattern})"


def test_the_template_stays_readable():
    """No file rule may match .env.example (a broad `.env.*` would; ADR-0009)."""
    deny = json.loads(read(".claude/settings.json"))["permissions"]["deny"]
    file_rules = [rule for rule in deny if rule.startswith(("Read(", "Edit(", "Write("))]
    targets = [rule.split("(", 1)[1].rstrip(")") for rule in file_rules]
    assert targets, "no file rules found, so nothing was checked"
    for target in targets:
        for path in (".env.example", "services/ledger/.env.example"):
            assert not glob_matches(target, path), f"{target} would block {path}"


def glob_matches(pattern: str, path: str) -> bool:
    """gitignore-style match of a permission path: `**/` any directories, `*` and `?` within one name."""
    pattern = pattern.removeprefix("./")
    regex = ""
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            regex, i = regex + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            regex, i = regex + ".*", i + 2
        elif pattern[i] == "*":
            regex, i = regex + "[^/]*", i + 1
        elif pattern[i] == "?":
            regex, i = regex + "[^/]", i + 1
        else:
            regex, i = regex + re.escape(pattern[i]), i + 1
    return re.fullmatch(regex, path) is not None


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("./**/*.env", "prod.env", True),
        ("./**/*.env", "a/b/deny-canary.env", True),
        ("./*.env", ".env", True),
        ("./.env.*", ".env.example", True),  # why the broad rule had to go
        ("./**/.env.local", "x/.env.local", True),
        ("./secrets/**", ".env.example", False),
        ("./**/*.env", ".env.example", False),
    ],
)
def test_glob_matches_knows_the_cases_that_matter(pattern, path, expected):
    # The template test above is only as good as this matcher: check it on known answers (rule 7).
    assert glob_matches(pattern, path) is expected


def walk_files(root: Path) -> list[str]:
    """Every file under root (tracked, untracked and ignored alike), as posix paths; tool caches skipped."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        found += [Path(dirpath, name).relative_to(root).as_posix() for name in filenames]
    return sorted(found)


def env_files(paths: list[str]) -> list[str]:
    """Files named like an env file, except the template. Names only: no file is ever opened."""
    return [p for p in paths if ENV_NAME.fullmatch(p.rsplit("/", 1)[-1]) and p.rsplit("/", 1)[-1] != TEMPLATE]


def not_denied_to_read(files: list[str], deny: list[str], prefix: str = "") -> list[str]:
    """The files no Read rule matches. `prefix` maps repo paths onto a parent folder's rules."""
    targets = [rule[5:-1] for rule in deny if rule.startswith("Read(") and rule.endswith(")")]
    assert targets, "no Read rules found, so nothing was checked"
    return [f for f in files if not any(glob_matches(t, prefix + f) for t in targets)]


def test_every_env_file_in_the_repo_is_denied_to_read():
    """An `.env.qa` that no named rule covers would be readable (ADR-0009's known gap): fail and name it."""
    paths = walk_files(ROOT)
    assert TEMPLATE in paths, "the walk did not see the template, so it scanned the wrong place"
    deny = json.loads(read(".claude/settings.json"))["permissions"]["deny"]
    open_files = not_denied_to_read(env_files(paths), deny)
    assert not open_files, f"add a Read deny rule (and Edit/Write) for: {open_files}"


def test_every_env_file_in_the_repo_is_denied_at_the_project1_level():
    """Same check against the parent folder's rules, which apply to sessions started there. Local only."""
    if not PROJECT1_SETTINGS.exists():
        pytest.skip("no project1 settings here (CI): the repo-level test above still runs")
    deny = json.loads(PROJECT1_SETTINGS.read_text(encoding="utf-8"))["permissions"]["deny"]
    open_files = not_denied_to_read(env_files(walk_files(ROOT)), deny, prefix=f"{ROOT.name}/")
    assert not open_files, f"add a Read deny rule to {PROJECT1_SETTINGS} for: {open_files}"


def test_the_env_file_check_catches_an_uncovered_variant(tmp_path):
    # Rule 7: prove the check fails when it should, on planted names (empty files, no values).
    for rel in (".env", ".env.qa", ".env.example", "sub/.env.local", "sub/qa.env", "app.py", ".venv/.env.qa"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).touch()
    deny = ["Read(./.env)", "Read(./**/.env.local)", "Read(./**/*.env)", "Bash(cat .env.qa)"]
    files = env_files(walk_files(tmp_path))
    assert files == [".env", ".env.qa", "sub/.env.local", "sub/qa.env"]
    assert not_denied_to_read(files, deny) == [".env.qa"]
    assert not_denied_to_read(files, [*deny, "Read(./**/.env.qa)"]) == []
    assert not_denied_to_read([".env.qa"], ["Read(./**/.env.qa)"], prefix="repo/") == []


def test_gitleaks_is_pinned_to_one_version_everywhere():
    for rel in (".pre-commit-config.yaml", "scripts/secrets_scan.ps1", "Makefile"):
        text = read(rel)
        versions = set(re.findall(r"ghcr\.io/gitleaks/gitleaks:([\w.\-]+)", text))
        assert versions == {GITLEAKS.rsplit(":", 1)[1]}, f"{rel}: {versions}"


def test_secrets_scan_refuses_a_scan_of_nothing():
    text = read("scripts/secrets_scan.ps1")
    assert "commits scanned" in text and "-lt 1" in text, "0 commits scanned must fail (rule 7)"


def test_new_env_never_overwrites_and_never_prints_a_value():
    text = read("scripts/new_env.ps1")
    assert "if (Test-Path .env)" in text
    printed = re.findall(r"Write-Host[^\n]*", text)
    assert printed and not any("New-Secret" in line or "$line" in line for line in printed)
    # Live credentials are never generated: the owner types those, only after approving their use.
    for name in ("ANTHROPIC_API_KEY", "SLACK_WEBHOOK_URL", "STAGE9_API_TOKEN"):
        assert f'"{name}"' not in text


def test_pre_commit_blocks_private_keys():
    assert "PRIVATE KEY-----" in read(".pre-commit-config.yaml")
