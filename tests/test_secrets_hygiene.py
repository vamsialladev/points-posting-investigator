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
