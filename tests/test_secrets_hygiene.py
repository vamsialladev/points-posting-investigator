"""Secrets stay out of Git, images and Claude Code's reach (rule 4, spec 0.3 and Part I)."""

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GITLEAKS = "ghcr.io/gitleaks/gitleaks:v8.30.1"


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
