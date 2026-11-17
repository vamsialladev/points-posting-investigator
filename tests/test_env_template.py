""".env.example never holds a real-looking value (ADR-0009, standing rule 4).

The template is readable by design (Claude Code's deny rules leave it open), so it must stay safe to read: names,
comments and harmless defaults only. Two layers:
- secret shapes (API keys, tokens, webhooks, private keys, a password written inside a URL, JWTs) are refused
  anywhere in the file, comments included;
- every value of a secret variable is empty, and no other value looks like a random credential.
The detector is tested on planted examples first, so a broken detector can't pass the real file (rule 7).
"""

import re
from pathlib import Path

import pytest
from dotenv import dotenv_values

from app.preflight import SECRET_NAMES

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / ".env.example"

SECRET_SHAPES: dict[str, re.Pattern[str]] = {
    "an Anthropic API key": re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    "a GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "an AWS access key ID": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "a Slack token or webhook": re.compile(r"xox[abposr]-[A-Za-z0-9\-]{10,}|hooks\.slack\.com/services/\S+"),
    "a private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "a password inside a URL": re.compile(r"://[^/\s:@]+:(?!\$\{)[^@\s/]+@"),
    "a JWT": re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
}
RANDOM_LOOKING = re.compile(r"[A-Za-z0-9+/_=\-]{24,}")


def shape_problems(text: str) -> list[str]:
    """Secret shapes anywhere in the text, by line number and kind only (never the value)."""
    problems = []
    for number, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in SECRET_SHAPES.items():
            if pattern.search(line):
                problems.append(f"line {number}: looks like {kind}")
    return problems


def value_problems(name: str, value: str) -> list[str]:
    """A template value that looks real: any value for a secret name, or a random-looking credential."""
    value = value.strip()
    if not value:
        return []
    if name in SECRET_NAMES and not (name == "DATABASE_URL" and "${POSTGRES_PASSWORD}" in value):
        return [f"{name} is a secret but the template gives it a value"]
    for run in RANDOM_LOOKING.findall(value):
        if re.search(r"[A-Za-z]", run) and re.search(r"\d", run):
            return [f"{name} has a random-looking value ({len(run)} characters of letters and digits)"]
    return []


def template_problems(text: str, values: dict[str, str | None]) -> list[str]:
    problems = shape_problems(text)
    for name, value in values.items():
        problems += value_problems(name, value or "")
    return problems


# ---------- the detector, on known answers ----------

# Fake, and split with "+" so the full shape exists only at runtime: secret scanners (gitleaks, GitHub push
# protection) must never see a credential-shaped string in this file.
FAKE_ANTHROPIC = "sk-" + "ant-api03-AbCdEf0123456789"
PLANTED = [
    ("ANTHROPIC_API_KEY", FAKE_ANTHROPIC),
    ("SOME_TOKEN", "ghp" + "_0123456789abcdefghijABCDEFGHIJ"),
    ("SOME_TOKEN", "github" + "_pat_11ABCDEFG0123456789_abcdefghij"),
    ("AWS_KEY", "AK" + "IAABCDEFGHIJKLMNOP"),
    ("SLACK_WEBHOOK_URL", "https://hooks.slack" + ".com/services/T000/B000/XXXX"),
    ("SLACK_BOT", "xo" + "xb-1234567890-abcdefghij"),
    ("DATABASE_URL", "postgresql+psycopg://points:" + "hunter2realpw@db.example.test:5432/points"),
    ("SESSION", "ey" + "JhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnopqrstu"),
    ("APP_SECRET_KEY", "anything-at-all"),
    ("SOMETHING_ELSE", "q8Zr2Kd9" + "Lm4Xw7Pn3Vb6Tc1Hy5"),
]


@pytest.mark.parametrize(("name", "value"), PLANTED)
def test_the_detector_flags_planted_real_looking_values(name, value):
    text = f"{name}={value}\n"
    assert template_problems(text, {name: value}), f"{name}: the detector missed a real-looking value"


def test_a_planted_key_in_a_comment_is_flagged_too():
    assert shape_problems(f"# my key: {FAKE_ANTHROPIC}\n") == ["line 1: looks like an Anthropic API key"]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DATABASE_URL", "postgresql+psycopg://points:${POSTGRES_PASSWORD}@localhost:5432/points"),
        ("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        ("LEDGER_API_URL", "http://localhost:8020"),
        ("LLM_BUDGET_USD_DAILY", "5.00"),
        ("AI_PROVIDER", "mock"),
        ("ANTHROPIC_MODEL", "claude-haiku-5-5"),
        ("APP_SECRET_KEY", ""),
    ],
)
def test_the_detector_leaves_safe_defaults_alone(name, value):
    assert template_problems(f"{name}={value}\n", {name: value}) == []


def test_problems_never_include_the_value():
    value = FAKE_ANTHROPIC
    problems = template_problems(f"ANTHROPIC_API_KEY={value}\n", {"ANTHROPIC_API_KEY": value})
    assert problems and all(value not in problem for problem in problems)


# ---------- the real template ----------


def test_env_example_holds_no_real_looking_value():
    text = TEMPLATE.read_text(encoding="utf-8")
    values = dotenv_values(TEMPLATE, interpolate=False)
    assert len(values) >= 30, "the template parsed to almost nothing, so nothing was checked"
    assert template_problems(text, values) == []
