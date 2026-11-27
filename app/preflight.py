"""Configuration readiness per operating profile, without ever printing a value (spec 0.3, Appendix B).

    python -m app.preflight --profile core
    python -m app.preflight --profile live-ai --json

Each known variable is reported as `set`, `missing` or `invalid format`, with where it came from (`environment`
or `.env`). The process environment overrides `.env`. Exit code 0 = the profile is ready, 1 = not ready,
2 = usage error. Ported from Stage 9's `app/preflight.py` (its ADR-0014); Stage 10 decisions: ADR-0006.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

Check = Callable[[str], bool]

PROFILES_ALLOWED = ("core", "observability", "automation", "live-ai", "stage9-adapter", "deploy")
PROVIDERS = ("mock", "anthropic")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "db", "postgres", "kafka", "ledger", "schema-registry"}
# Long-lived cloud keys are refused in every profile: deployment uses AWS SSO only (Appendix B).
FORBIDDEN_NAMES = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")


# ---------- format checks (pure; they see a value but never return or print it) ----------


def _nonempty(value: str) -> bool:
    return bool(value.strip())


def _min_len(n: int) -> Check:
    return lambda value: len(value.strip()) >= n


def _enum(*options: str) -> Check:
    return lambda value: value.strip() in options


def _bool(value: str) -> bool:
    return value.strip().lower() in {"true", "false"}


def _positive_number(value: str) -> bool:
    try:
        return float(value) > 0
    except ValueError:
        return False


def _regex(pattern: str) -> Check:
    compiled = re.compile(pattern)
    return lambda value: compiled.fullmatch(value.strip()) is not None


def _prefix(prefix: str, min_total: int) -> Check:
    return lambda value: value.startswith(prefix) and len(value) >= min_total


def _url(*schemes: str) -> Check:
    def check(value: str) -> bool:
        parts = urlsplit(value.strip())
        return parts.scheme in schemes and bool(parts.hostname)

    return check


def _postgres_url(value: str) -> bool:
    """A Postgres URL with a host, a user and a non-empty password (an empty one means POSTGRES_PASSWORD is unset)."""
    parts = urlsplit(value.strip())
    return (
        parts.scheme in {"postgresql", "postgresql+psycopg", "postgres"}
        and bool(parts.hostname)
        and bool(parts.username)
        and bool(parts.password)
    )


def _bootstrap_servers(value: str) -> bool:
    """Comma-separated host:port pairs, as Kafka clients take them."""
    return re.fullmatch(r"[A-Za-z0-9.\-]+:\d{2,5}(,[A-Za-z0-9.\-]+:\d{2,5})*", value.strip()) is not None


@dataclass(frozen=True)
class Var:
    name: str
    check: Check
    expected: str
    secret: bool = False


VARS: dict[str, Var] = {
    v.name: v
    for v in [
        # Core
        Var("APP_PROFILE", _enum(*PROFILES_ALLOWED), "one of " + ", ".join(PROFILES_ALLOWED)),
        Var("APP_SECRET_KEY", _min_len(32), "at least 32 characters", secret=True),
        Var("PUBLIC_DEMO_MODE", _bool, "true or false"),
        Var("LOG_LEVEL", _enum("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"), "DEBUG, INFO, WARNING, ERROR"),
        Var("POSTGRES_USER", _nonempty, "non-empty"),
        Var("POSTGRES_PASSWORD", _min_len(8), "at least 8 characters", secret=True),
        Var("POSTGRES_DB", _nonempty, "non-empty"),
        Var("DATABASE_URL", _postgres_url, "postgresql URL with user, password and host", secret=True),
        # Runtime database roles (RFC-0001 D9): each service logs in with only its own rights.
        Var("LEDGER_DB_PASSWORD", _min_len(8), "at least 8 characters", secret=True),
        Var("POSTING_DB_PASSWORD", _min_len(8), "at least 8 characters", secret=True),
        Var("RELAY_DB_PASSWORD", _min_len(8), "at least 8 characters", secret=True),
        Var("OPS_DB_PASSWORD", _min_len(8), "at least 8 characters", secret=True),
        # Kafka
        Var("KAFKA_BOOTSTRAP_SERVERS", _bootstrap_servers, "host:port[,host:port]"),
        Var("SCHEMA_REGISTRY_URL", _url("http", "https"), "an http(s) URL"),
        # Ledger mock
        Var("LEDGER_API_URL", _url("http", "https"), "an http(s) URL"),
        Var("LEDGER_API_TOKEN", _min_len(12), "at least 12 characters", secret=True),
        # AI
        Var("AI_PROVIDER", _enum(*PROVIDERS), "one of " + ", ".join(PROVIDERS)),
        Var("ANTHROPIC_API_KEY", _prefix("sk-ant-", 24), "starts with sk-ant-", secret=True),
        Var("ANTHROPIC_MODEL", _regex(r"claude-[a-z0-9][a-z0-9.\-]*"), "an exact Claude model ID (claude-...)"),
        Var("LLM_BUDGET_USD_PER_RUN", _positive_number, "a positive number of US dollars"),
        Var("LLM_BUDGET_USD_DAILY", _positive_number, "a positive number of US dollars"),
        # Observability
        Var("OTEL_EXPORTER_OTLP_ENDPOINT", _url("http", "https"), "an http(s) URL"),
        Var("GRAFANA_ADMIN_PASSWORD", _min_len(12), "at least 12 characters", secret=True),
        # Automation
        Var("N8N_ENCRYPTION_KEY", _min_len(24), "at least 24 characters", secret=True),
        Var("N8N_WEBHOOK_URL", _url("http", "https"), "an http(s) URL"),
        Var("AUTOMATION_WEBHOOK_SECRET", _min_len(32), "at least 32 characters", secret=True),
        Var("MOCK_SLACK_URL", _url("http", "https"), "an http(s) URL"),
        Var("MOCK_JIRA_URL", _url("http", "https"), "an http(s) URL"),
        Var("SLACK_WEBHOOK_URL", _prefix("https://hooks.slack.com/", 40), "a Slack incoming-webhook URL", secret=True),
        # Stage 9 adapter
        Var("STAGE9_API_URL", _url("http", "https"), "an http(s) URL"),
        Var("STAGE9_API_TOKEN", _min_len(16), "at least 16 characters", secret=True),
        # Deployment (AWS SSO only)
        Var("AWS_PROFILE", _nonempty, "an AWS SSO profile name"),
        Var("AWS_REGION", _regex(r"[a-z]{2}(-gov)?-[a-z]+-\d"), "an AWS region such as us-east-1"),
        # Feature flags
        Var("FEATURE_LIVE_AI", _bool, "true or false"),
        Var("FEATURE_AUTO_INVESTIGATE", _bool, "true or false"),
        Var("FEATURE_RECOVERY_EXECUTION", _bool, "true or false"),
        Var("FEATURE_N8N", _bool, "true or false"),
    ]
}

SECRET_NAMES = frozenset(name for name, var in VARS.items() if var.secret)

PROVIDER_VARS: dict[str, tuple[str, ...]] = {
    "mock": (),
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"),
}

_CORE = (
    "APP_PROFILE",
    "APP_SECRET_KEY",
    "PUBLIC_DEMO_MODE",
    "LOG_LEVEL",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "DATABASE_URL",
    "LEDGER_DB_PASSWORD",
    "POSTING_DB_PASSWORD",
    "RELAY_DB_PASSWORD",
    "OPS_DB_PASSWORD",
    "KAFKA_BOOTSTRAP_SERVERS",
    "SCHEMA_REGISTRY_URL",
    "LEDGER_API_URL",
    "LEDGER_API_TOKEN",
    "AI_PROVIDER",
    "LLM_BUDGET_USD_PER_RUN",
    "LLM_BUDGET_USD_DAILY",
    "FEATURE_LIVE_AI",
    "FEATURE_AUTO_INVESTIGATE",
    "FEATURE_RECOVERY_EXECUTION",
)
_OBSERVABILITY = ("OTEL_EXPORTER_OTLP_ENDPOINT", "GRAFANA_ADMIN_PASSWORD")
_AUTOMATION = (
    "N8N_ENCRYPTION_KEY",
    "N8N_WEBHOOK_URL",
    "AUTOMATION_WEBHOOK_SECRET",
    "MOCK_SLACK_URL",
    "MOCK_JIRA_URL",
    "FEATURE_N8N",
)


# ---------- reading configuration ----------


@dataclass(frozen=True)
class Settings:
    """Known variable values and where each came from. Values stay in memory; nothing here prints them."""

    values: dict[str, str]
    sources: dict[str, str]
    unknown_in_file: tuple[str, ...] = ()
    reference_problems: tuple[str, ...] = ()
    forbidden_present: tuple[str, ...] = ()


_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)")


def reference_problems(raw: Mapping[str, str | None], environ: Mapping[str, str]) -> list[str]:
    """`${NAME}` uses that will expand to a blank string, by name only.

    python-dotenv and Docker Compose both expand references top to bottom, so a variable used on a line above its own
    definition is blank at that point (unless the process environment supplies it). Found in Stage 9's first run.
    """
    order = {name: index for index, name in enumerate(raw)}
    problems = []
    for index, (name, value) in enumerate(raw.items()):
        for ref in dict.fromkeys(_REFERENCE.findall(value or "")):
            if environ.get(ref, "").strip():
                continue
            if ref not in order:
                problems.append(
                    f"{name} uses ${{{ref}}}, which is not defined in .env, so it expands to a blank string"
                )
            elif order[ref] > index:
                problems.append(
                    f"{name} uses ${{{ref}}} above the line that defines {ref}, so it expands to a blank string; "
                    f"move {ref} above {name}"
                )
    return problems


def load_settings(env_file: Path | None, environ: Mapping[str, str]) -> Settings:
    file_values: dict[str, str] = {}
    unknown: list[str] = []
    references: list[str] = []
    forbidden: list[str] = []
    if env_file is not None and env_file.is_file():
        references = reference_problems(dotenv_values(env_file, interpolate=False), environ)
        for key, value in dotenv_values(env_file).items():
            if key in VARS:
                file_values[key] = value or ""
            elif key in FORBIDDEN_NAMES:
                if (value or "").strip():
                    forbidden.append(key)
            else:
                unknown.append(key)
    forbidden += [name for name in FORBIDDEN_NAMES if environ.get(name, "").strip() and name not in forbidden]
    values: dict[str, str] = {}
    sources: dict[str, str] = {}
    for name in VARS:
        if environ.get(name, "").strip():
            values[name], sources[name] = environ[name], "environment"
        elif file_values.get(name, "").strip():
            values[name], sources[name] = file_values[name], ".env"
    return Settings(values, sources, tuple(sorted(unknown)), tuple(references), tuple(sorted(forbidden)))


# ---------- profiles ----------


def _flag(settings: Settings, name: str) -> bool:
    return settings.values.get(name, "").strip().lower() == "true"


def _provider(settings: Settings) -> str:
    return settings.values.get("AI_PROVIDER", "").strip()


def _is_local(url: str) -> bool:
    return (urlsplit(url.strip()).hostname or "") in LOCAL_HOSTS


def _check_provider_consistency(settings: Settings) -> list[str]:
    if _flag(settings, "FEATURE_LIVE_AI") and _provider(settings) == "mock":
        return ["FEATURE_LIVE_AI is true but AI_PROVIDER is mock: choose a provider or turn live AI off"]
    if _provider(settings) not in ("", "mock") and not _flag(settings, "FEATURE_LIVE_AI"):
        return ["AI_PROVIDER is a live provider but FEATURE_LIVE_AI is not true: live calls stay off until both agree"]
    return []


def _check_budgets(settings: Settings) -> list[str]:
    try:
        per_run = float(settings.values.get("LLM_BUDGET_USD_PER_RUN", ""))
        daily = float(settings.values.get("LLM_BUDGET_USD_DAILY", ""))
    except ValueError:
        return []
    if per_run > daily:
        return ["LLM_BUDGET_USD_PER_RUN is larger than LLM_BUDGET_USD_DAILY"]
    return []


def _check_forbidden(settings: Settings) -> list[str]:
    return [
        f"{name} is set: long-lived AWS keys are not allowed; use an AWS SSO profile (AWS_PROFILE)"
        for name in settings.forbidden_present
    ]


def _check_live(settings: Settings) -> list[str]:
    problems = []
    if _provider(settings) in ("", "mock"):
        problems.append("live-ai needs AI_PROVIDER=anthropic, not mock")
    if not _flag(settings, "FEATURE_LIVE_AI"):
        problems.append("live-ai needs FEATURE_LIVE_AI=true")
    return problems


def _check_automation(settings: Settings) -> list[str]:
    if not _flag(settings, "FEATURE_N8N"):
        return ["automation needs FEATURE_N8N=true"]
    return []


def _check_hosted(settings: Settings) -> list[str]:
    problems = []
    for name in ("DATABASE_URL", "LEDGER_API_URL", "SCHEMA_REGISTRY_URL"):
        if name in settings.values and _is_local(settings.values[name]):
            problems.append(f"{name} points at a local host; the deploy profile needs the hosted service")
    if settings.values.get("LOG_LEVEL", "").strip() == "DEBUG":
        problems.append("LOG_LEVEL is DEBUG; the deploy profile must not run in debug mode")
    return problems


# Values that are someone's default, a template's or a test's: never acceptable outside a laptop (Stage 9 DEL-05).
KNOWN_DEFAULTS = frozenset({"admin", "password", "changeme", "secret", "postgres", "test", "demo", "points"})
DEFAULT_MARKERS = ("throwaway", "change-me", "changeme", "example", "check-only", "for-tests", "placeholder")
HOSTED_MIN_SECRET = 16


def _looks_default(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered in KNOWN_DEFAULTS or any(marker in lowered for marker in DEFAULT_MARKERS)


def _check_no_default_credentials(settings: Settings) -> list[str]:
    """Hosted profile: no secret may be a known default, a template or test value, or short. Names only."""
    problems = []
    for name in sorted(SECRET_NAMES):
        value = settings.values.get(name, "")
        if not value.strip():
            continue
        secret = (urlsplit(value).password or "") if name == "DATABASE_URL" else value
        if _looks_default(secret):
            problems.append(f"{name} looks like a default or test value; set a real secret in the platform's store")
        elif len(secret.strip()) < HOSTED_MIN_SECRET:
            problems.append(f"{name} is shorter than {HOSTED_MIN_SECRET} characters; hosted profiles need longer")
    return problems


@dataclass(frozen=True)
class Profile:
    name: str
    description: str
    required: tuple[str, ...]
    checks: tuple[Callable[[Settings], list[str]], ...] = ()
    accepts_app_profile: tuple[str, ...] = field(default=())

    def app_profiles(self) -> tuple[str, ...]:
        return (self.name, *self.accepts_app_profile)


_COMMON_CHECKS = (_check_provider_consistency, _check_budgets, _check_forbidden)

PROFILES: dict[str, Profile] = {
    p.name: p
    for p in [
        Profile(
            "core",
            "Default. Local Kafka, Postgres and ledger mock in Docker; synthetic data; offline mock AI.",
            _CORE,
            _COMMON_CHECKS,
        ),
        Profile(
            "observability",
            "Core plus the OpenTelemetry collector, trace store, Prometheus and Grafana (local).",
            _CORE + _OBSERVABILITY,
            _COMMON_CHECKS,
            accepts_app_profile=("core",),
        ),
        Profile(
            "automation",
            "Core plus self-hosted n8n and the mock Slack/Jira endpoints (v2). A real Slack webhook needs approval.",
            _CORE + _AUTOMATION,
            (*_COMMON_CHECKS, _check_automation),
            accepts_app_profile=("core",),
        ),
        Profile(
            "live-ai",
            "Core plus live Claude calls, with both budget caps. Used only after the owner approves a cap.",
            _CORE + PROVIDER_VARS["anthropic"],
            (*_COMMON_CHECKS, _check_live),
            accepts_app_profile=("core",),
        ),
        Profile(
            "stage9-adapter",
            "Core plus the optional Stage 9 adapter that flags matching missing-points cases (v2).",
            (*_CORE, "STAGE9_API_URL", "STAGE9_API_TOKEN"),
            _COMMON_CHECKS,
            accepts_app_profile=("core",),
        ),
        Profile(
            "deploy",
            "A hosted deployment (v2, only after the owner approves an option and budget). AWS SSO only.",
            (*_CORE, "AWS_PROFILE", "AWS_REGION"),
            (*_COMMON_CHECKS, _check_hosted, _check_no_default_credentials),
        ),
    ]
}

# Feature -> the variables that unlock it.
FEATURES: dict[str, tuple[str, ...]] = {
    "Offline pipeline and investigator (mock AI, local Docker)": (
        "APP_SECRET_KEY",
        "DATABASE_URL",
        "LEDGER_DB_PASSWORD",
        "POSTING_DB_PASSWORD",
        "RELAY_DB_PASSWORD",
        "OPS_DB_PASSWORD",
        "KAFKA_BOOTSTRAP_SERVERS",
        "LEDGER_API_TOKEN",
    ),
    "Live Claude runs (arm C live; needs the owner's OK and a cap)": ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"),
    "Traces and dashboards (observability profile)": _OBSERVABILITY,
    "n8n flow and mock Slack/Jira (v2)": _AUTOMATION,
    "Real Slack webhook (v2, owner approval only)": ("SLACK_WEBHOOK_URL",),
    "Stage 9 adapter (v2)": ("STAGE9_API_URL", "STAGE9_API_TOKEN"),
    "AWS deployment (v2, owner approval only)": ("AWS_PROFILE", "AWS_REGION"),
}


# ---------- the report ----------


def status_of(settings: Settings, name: str) -> str:
    if name not in settings.values:
        return "missing"
    return "set" if VARS[name].check(settings.values[name]) else "invalid format"


@dataclass(frozen=True)
class Report:
    profile: str
    required: dict[str, str]
    optional: dict[str, str]
    sources: dict[str, str]
    problems: list[str]
    features: dict[str, list[str]]
    unknown_in_file: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.problems

    def as_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "ready": self.ready,
            "required": self.required,
            "optional": self.optional,
            "sources": self.sources,
            "problems": self.problems,
            "features": {
                name: ("unlocked" if not needs else {"blocked": needs}) for name, needs in self.features.items()
            },
            "unknown_in_file": list(self.unknown_in_file),
        }


def build_report(profile_name: str, settings: Settings) -> Report:
    profile = PROFILES[profile_name]
    provider_vars = PROVIDER_VARS.get(_provider(settings), ())
    required_names = list(dict.fromkeys(profile.required + provider_vars))
    required = {name: status_of(settings, name) for name in required_names}
    optional = {name: status_of(settings, name) for name in VARS if name not in required}

    problems = list(settings.reference_problems)
    problems += [
        f"{name} is {status} (expected {VARS[name].expected})" for name, status in required.items() if status != "set"
    ]
    for name, status in optional.items():
        if status == "invalid format":
            problems.append(f"{name} is set but has an invalid format (expected {VARS[name].expected})")
    app_profile = settings.values.get("APP_PROFILE", "").strip()
    if app_profile in PROFILES_ALLOWED and app_profile not in profile.app_profiles():
        problems.append(f"APP_PROFILE names a different profile than --profile {profile_name}")
    for check in profile.checks:
        problems.extend(check(settings))

    features = {
        feature: [name for name in needs if status_of(settings, name) != "set"] for feature, needs in FEATURES.items()
    }
    return Report(
        profile_name, required, optional, dict(settings.sources), problems, features, settings.unknown_in_file
    )


def render_text(report: Report) -> str:
    lines = [
        f"Preflight - profile: {report.profile}",
        PROFILES[report.profile].description,
        "Values are never printed. Status only: set / missing / invalid format.",
        "",
        "Required for this profile",
    ]
    width = max(len(name) for name in VARS) + 2
    for name, status in report.required.items():
        lines.append(f"  {name:<{width}}{status:<16}{report.sources.get(name, '-')}")
    lines += ["", "Optional (unlock other profiles and features)"]
    for name, status in report.optional.items():
        lines.append(f"  {name:<{width}}{status:<16}{report.sources.get(name, '-')}")
    lines += ["", "Features"]
    for feature, needs in report.features.items():
        lines.append(f"  unlocked  {feature}" if not needs else f"  blocked   {feature}: needs {', '.join(needs)}")
    if report.unknown_in_file:
        lines += ["", "Unknown names in .env (typo?): " + ", ".join(report.unknown_in_file)]
    lines.append("")
    if report.ready:
        lines.append("Result: READY")
    else:
        lines.append(f"Result: NOT READY ({len(report.problems)} problem{'s' if len(report.problems) != 1 else ''})")
        lines += [f"  - {problem}" for problem in report.problems]
    return "\n".join(lines)


def main(argv: list[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.preflight", description="Configuration readiness per profile; never prints values."
    )
    parser.add_argument("--profile", choices=PROFILES_ALLOWED, default=None, help="defaults to APP_PROFILE, then core")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="default: .env in the current folder")
    parser.add_argument("--json", action="store_true", help="machine-readable output (still no values)")
    args = parser.parse_args(argv)

    settings = load_settings(args.env_file, os.environ if environ is None else environ)
    profile = args.profile or settings.values.get("APP_PROFILE", "").strip() or "core"
    if profile not in PROFILES:
        profile = "core"
    report = build_report(profile, settings)
    print(json.dumps(report.as_dict(), indent=2) if args.json else render_text(report))
    return 0 if report.ready else 1


if __name__ == "__main__":
    sys.exit(main())
