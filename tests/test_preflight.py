"""Preflight: readiness per profile, and no value ever reaches the output (spec 0.3, Appendix B).

Ported from Stage 9's tests/test_preflight.py and adapted to Stage 10's variables and profiles.
"""

import json
from pathlib import Path

import pytest
from dotenv import dotenv_values

from app import preflight
from app.pipeline import kafka_auth
from app.preflight import PROFILES, VARS, build_report, load_settings, main

ROOT = Path(__file__).resolve().parent.parent

# Valid-looking, obviously fake values. Each is distinctive so a leak into the output is easy to spot.
FAKE = {
    "APP_PROFILE": "core",
    "APP_SECRET_KEY": "fake-app-secret-key-0123456789abcdefghijklmnop",
    "PUBLIC_DEMO_MODE": "false",
    "LOG_LEVEL": "INFO",
    # Distinctive on purpose: a plain "points" also appears in report text ("points at a local host"), which made
    # the leak test below flag a non-leak on its first run.
    "POSTGRES_USER": "fakepguser",
    "POSTGRES_PASSWORD": "fake-pg-password-7781",
    "POSTGRES_DB": "fakepgdb",
    "DATABASE_URL": "postgresql+psycopg://fakepguser:fake-pg-password-7781@localhost:5432/fakepgdb",
    "LEDGER_DB_PASSWORD": "fake-ledger-db-pw-3301",
    "POSTING_DB_PASSWORD": "fake-posting-db-pw-3302",
    "RELAY_DB_PASSWORD": "fake-relay-db-pw-3303",
    "OPS_DB_PASSWORD": "fake-ops-db-pw-3304",
    "INVESTIGATOR_DB_PASSWORD": "fake-investigator-db-pw-3305",
    **{name: f"fake-kafka-login-{n:02d}" for n, name in enumerate(kafka_auth.PASSWORD_VARIABLES)},
    "KAFKA_BOOTSTRAP_SERVERS": "localhost:9092",
    "SCHEMA_REGISTRY_URL": "http://localhost:8081",
    "LEDGER_API_URL": "http://localhost:8020",
    "LEDGER_API_TOKEN": "fake-ledger-token-4410",
    "AI_PROVIDER": "mock",
    "ANTHROPIC_API_KEY": "sk-ant-fake-key-do-not-use-000000000000",
    "ANTHROPIC_MODEL": "claude-haiku-5-5",
    "LLM_BUDGET_USD_PER_RUN": "1.00",
    "LLM_BUDGET_USD_DAILY": "5.00",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://fake-otel-collector.test:4318",
    "GRAFANA_ADMIN_PASSWORD": "fake-grafana-admin-5566",
    "N8N_ENCRYPTION_KEY": "fake-n8n-encryption-key-1234567890",
    "N8N_WEBHOOK_URL": "http://fake-n8n.test:5678/webhook/incident",
    "AUTOMATION_WEBHOOK_SECRET": "fake-automation-webhook-secret-0123456789",
    "MOCK_SLACK_URL": "http://fake-mock-slack.test:8031",
    "MOCK_JIRA_URL": "http://fake-mock-jira.test:8032",
    "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/TFAKE/BFAKE/fakefakefakefake",
    "STAGE9_API_URL": "http://fake-stage9.test:8010",
    "STAGE9_API_TOKEN": "fake-stage9-token-12345678",
    "AWS_PROFILE": "fake-sso-profile-name",
    "AWS_REGION": "us-east-1",
    "FEATURE_LIVE_AI": "false",
    "FEATURE_AUTO_INVESTIGATE": "true",
    "FEATURE_RECOVERY_EXECUTION": "true",
    "FEATURE_N8N": "false",
}

CORE_KEYS = list(preflight._CORE)


def settings_from(values: dict[str, str], environ: dict[str, str] | None = None, tmp_path: Path | None = None):
    if tmp_path is None:
        return load_settings(None, values)
    env = tmp_path / ".env"
    env.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    return load_settings(env, environ or {})


def core(**overrides: str) -> dict[str, str]:
    values = {k: FAKE[k] for k in CORE_KEYS}
    values.update(overrides)
    return values


def test_the_six_profiles_are_defined():
    expected = {"core", "observability", "automation", "live-ai", "stage9-adapter", "deploy"}
    assert set(PROFILES) == expected
    assert set(preflight.PROFILES_ALLOWED) == set(PROFILES)


def test_fake_values_pass_every_format_check():
    # Guards the leak test below: every variable must be exercised as "set", not skipped as invalid.
    assert set(FAKE) == set(VARS)
    assert [name for name, value in FAKE.items() if not VARS[name].check(value)] == []


@pytest.mark.parametrize("as_json", [False, True])
def test_output_never_contains_values(tmp_path, capsys, as_json):
    env = tmp_path / ".env"
    env.write_text("".join(f"{k}={v}\n" for k, v in FAKE.items()), encoding="utf-8")
    for profile in PROFILES:
        main(["--profile", profile, "--env-file", str(env)] + (["--json"] if as_json else []), environ={})
        out = capsys.readouterr().out
        # APP_PROFILE's value is a profile name the report shows by design; short enum-like values (true, INFO,
        # mock) are too short to search for. Every other value must be absent.
        leaked = [name for name, value in FAKE.items() if name != "APP_PROFILE" and len(value) >= 6 and value in out]
        assert leaked == [], f"values of {leaked} appeared in the {profile} output"


def test_every_secret_variable_is_flagged_secret():
    looks_secret = {name for name in VARS if name.endswith(("KEY", "TOKEN", "SECRET", "PASSWORD"))}
    assert looks_secret <= preflight.SECRET_NAMES
    assert {"DATABASE_URL", "SLACK_WEBHOOK_URL"} <= preflight.SECRET_NAMES  # carry a password / are a credential


def test_template_env_is_not_ready_and_lists_missing(tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_text((ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    code = main(["--profile", "core", "--env-file", str(env)], environ={})
    out = capsys.readouterr().out
    assert code == 1
    assert "APP_SECRET_KEY" in out and "missing" in out
    assert "NOT READY" in out


def test_template_names_match_known_variables():
    template = dotenv_values(ROOT / ".env.example")
    assert set(template) == set(VARS), "every .env.example name is checked by preflight, and vice versa"


def test_template_defaults_are_mock_and_safe():
    template = dotenv_values(ROOT / ".env.example")
    assert template["APP_PROFILE"] == "core"
    assert template["AI_PROVIDER"] == "mock"
    assert template["FEATURE_LIVE_AI"] == "false"
    assert template["PUBLIC_DEMO_MODE"] == "false"
    for name in preflight.SECRET_NAMES - {"DATABASE_URL"}:
        assert template[name] in ("", None), f"{name} must be empty in the template"


def test_template_with_generated_local_values_is_ready_for_core(tmp_path):
    """What scripts\\new_env.ps1 produces: the template plus random local secrets, in the template's order."""
    generated = {
        "APP_SECRET_KEY": "x" * 48,
        "POSTGRES_PASSWORD": "p" * 24,
        "LEDGER_DB_PASSWORD": "l" * 24,
        "POSTING_DB_PASSWORD": "o" * 24,
        "RELAY_DB_PASSWORD": "r" * 24,
        "OPS_DB_PASSWORD": "p" * 24,
        "INVESTIGATOR_DB_PASSWORD": "i" * 24,
        **{name: "k" * 24 for name in kafka_auth.PASSWORD_VARIABLES},
        "LEDGER_API_TOKEN": "t" * 24,
    }
    lines = []
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        name = line.split("=", 1)[0]
        lines.append(f"{name}={generated[name]}" if name in generated and line == f"{name}=" else line)
    env = tmp_path / ".env"
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = build_report("core", load_settings(env, {}))
    assert report.problems == []
    assert report.required["DATABASE_URL"] == "set"  # ${POSTGRES_PASSWORD} is defined above it


def test_core_ready_with_local_values():
    report = build_report("core", settings_from(core()))
    assert report.problems == []
    assert report.ready


def test_missing_secret_key_is_not_ready():
    values = core()
    del values["APP_SECRET_KEY"]
    report = build_report("core", settings_from(values))
    assert report.required["APP_SECRET_KEY"] == "missing"
    assert not report.ready


def test_empty_postgres_password_makes_database_url_invalid(tmp_path):
    env = tmp_path / ".env"
    lines = [f"{k}={v}" for k, v in core().items() if k not in ("POSTGRES_PASSWORD", "DATABASE_URL")]
    lines += [
        "POSTGRES_PASSWORD=",
        "DATABASE_URL=postgresql+psycopg://points:${POSTGRES_PASSWORD}@localhost:5432/points",
    ]
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = build_report("core", load_settings(env, {}))
    assert report.required["POSTGRES_PASSWORD"] == "missing"
    assert report.required["DATABASE_URL"] == "invalid format"


def test_reference_above_its_definition_names_the_cause(tmp_path, capsys):
    env = tmp_path / ".env"
    head = [f"{k}={v}" for k, v in core().items() if k not in ("POSTGRES_PASSWORD", "DATABASE_URL")]
    tail = [
        "DATABASE_URL=postgresql+psycopg://points:${POSTGRES_PASSWORD}@localhost:5432/points",
        f"POSTGRES_PASSWORD={FAKE['POSTGRES_PASSWORD']}",
    ]
    env.write_text("\n".join(head + tail) + "\n", encoding="utf-8")
    report = build_report("core", load_settings(env, {}))
    assert report.required["DATABASE_URL"] == "invalid format"
    assert any("DATABASE_URL uses ${POSTGRES_PASSWORD} above the line that defines" in p for p in report.problems)
    main(["--profile", "core", "--env-file", str(env)], environ={})
    assert FAKE["POSTGRES_PASSWORD"] not in capsys.readouterr().out


def test_reference_to_an_undefined_variable_is_named():
    raw = {"DATABASE_URL": "postgresql+psycopg://points:${POSTGRES_PASSWORD}@localhost:5432/points"}
    assert any("which is not defined in .env" in p for p in preflight.reference_problems(raw, {}))
    assert preflight.reference_problems(raw, {"POSTGRES_PASSWORD": "from-the-shell"}) == []


def test_selected_provider_without_key_is_not_ready():
    report = build_report("core", settings_from(core(AI_PROVIDER="anthropic", FEATURE_LIVE_AI="true")))
    assert report.required["ANTHROPIC_API_KEY"] == "missing"
    assert report.required["ANTHROPIC_MODEL"] == "missing"
    assert not report.ready  # never a silent fall back to the mock provider


def test_live_flag_and_provider_must_agree():
    report = build_report("core", settings_from(core(FEATURE_LIVE_AI="true")))
    assert any("AI_PROVIDER is mock" in p for p in report.problems)
    values = core(AI_PROVIDER="anthropic", ANTHROPIC_API_KEY=FAKE["ANTHROPIC_API_KEY"], ANTHROPIC_MODEL="claude-x")
    report = build_report("core", settings_from(values))
    assert any("FEATURE_LIVE_AI is not true" in p for p in report.problems)


def test_live_ai_profile_requires_provider_flag_key_and_model():
    report = build_report("live-ai", settings_from(core()))
    assert any("AI_PROVIDER=anthropic" in p for p in report.problems)
    assert any("FEATURE_LIVE_AI=true" in p for p in report.problems)
    assert report.required["ANTHROPIC_API_KEY"] == "missing"
    ready = core(
        AI_PROVIDER="anthropic",
        FEATURE_LIVE_AI="true",
        ANTHROPIC_API_KEY=FAKE["ANTHROPIC_API_KEY"],
        ANTHROPIC_MODEL=FAKE["ANTHROPIC_MODEL"],
    )
    assert build_report("live-ai", settings_from(ready)).ready


def test_live_ai_is_never_ready_without_both_budget_caps():
    for cap in ("LLM_BUDGET_USD_PER_RUN", "LLM_BUDGET_USD_DAILY"):
        values = core(
            AI_PROVIDER="anthropic",
            FEATURE_LIVE_AI="true",
            ANTHROPIC_API_KEY=FAKE["ANTHROPIC_API_KEY"],
            ANTHROPIC_MODEL=FAKE["ANTHROPIC_MODEL"],
        )
        del values[cap]
        report = build_report("live-ai", settings_from(values))
        assert report.required[cap] == "missing" and not report.ready


def test_budget_per_run_above_daily():
    report = build_report("core", settings_from(core(LLM_BUDGET_USD_PER_RUN="9", LLM_BUDGET_USD_DAILY="5")))
    assert any("larger than" in p for p in report.problems)


@pytest.mark.parametrize("value", ["0", "-1", "free"])
def test_budgets_must_be_positive_numbers(value):
    report = build_report("core", settings_from(core(LLM_BUDGET_USD_DAILY=value)))
    assert report.required["LLM_BUDGET_USD_DAILY"] == "invalid format"


def test_invalid_format_is_reported_without_value():
    values = core(AI_PROVIDER="anthropic", FEATURE_LIVE_AI="true", ANTHROPIC_API_KEY="abc123xyz")
    report = build_report("core", settings_from(values))
    assert report.required["ANTHROPIC_API_KEY"] == "invalid format"
    assert all("abc123xyz" not in p for p in report.problems)


def test_optional_invalid_value_is_a_problem():
    report = build_report("core", settings_from(core(STAGE9_API_URL="not a url")))
    assert report.optional["STAGE9_API_URL"] == "invalid format"
    assert not report.ready


@pytest.mark.parametrize("servers", ["localhost", "kafka:9092,", "http://kafka:9092"])
def test_kafka_bootstrap_servers_format(servers):
    assert not VARS["KAFKA_BOOTSTRAP_SERVERS"].check(servers)
    assert VARS["KAFKA_BOOTSTRAP_SERVERS"].check("kafka-1:9092,kafka-2:9093")


def test_environment_overrides_file(tmp_path):
    settings = settings_from(core(), environ={"LOG_LEVEL": "WARNING"}, tmp_path=tmp_path)
    assert settings.values["LOG_LEVEL"] == "WARNING"
    assert settings.sources["LOG_LEVEL"] == "environment"
    assert settings.sources["APP_SECRET_KEY"] == ".env"


@pytest.mark.parametrize("name", preflight.FORBIDDEN_NAMES)
def test_long_lived_aws_keys_are_refused_by_name_only(tmp_path, capsys, name):
    env = tmp_path / ".env"
    env.write_text(
        "".join(f"{k}={v}\n" for k, v in core().items()) + f"{name}=AKIAFAKEFAKEFAKE1234\n", encoding="utf-8"
    )
    report = build_report("core", load_settings(env, {}))
    assert any(p.startswith(f"{name} is set: long-lived AWS keys") for p in report.problems)
    from_environ = build_report("deploy", load_settings(None, core() | {name: "AKIAFAKEFAKEFAKE1234"}))
    assert any(p.startswith(f"{name} is set") for p in from_environ.problems)
    main(["--env-file", str(env)], environ={})
    assert "AKIAFAKEFAKEFAKE1234" not in capsys.readouterr().out


def test_deploy_profile_rejects_local_services_and_debug():
    values = core(APP_PROFILE="deploy", LOG_LEVEL="DEBUG", AWS_PROFILE="x", AWS_REGION="us-east-1")
    report = build_report("deploy", settings_from(values))
    assert any("DATABASE_URL points at a local host" in p for p in report.problems)
    assert any("debug" in p for p in report.problems)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("APP_SECRET_KEY", "changeme-changeme-changeme-changeme"),
        ("LEDGER_API_TOKEN", "ci-only-throwaway"),
        ("LEDGER_API_TOKEN", "short-but-ok12"),
        ("DATABASE_URL", "postgresql+psycopg://points:password@db.managed.test:5432/points"),
    ],
)
def test_deploy_refuses_default_test_or_short_secrets_by_name_only(name, value):
    hosted = {
        "DATABASE_URL": "postgresql+psycopg://points:a-long-real-looking-secret-77@db.managed.test:5432/points",
        "LEDGER_API_URL": "https://ledger.managed.test",
        "SCHEMA_REGISTRY_URL": "https://registry.managed.test",
        "LEDGER_API_TOKEN": "a-long-real-looking-ledger-token-55",
    }
    values = core(APP_PROFILE="deploy", AWS_PROFILE="sso", AWS_REGION="us-east-1") | hosted | {name: value}
    report = build_report("deploy", settings_from(values))
    assert any(p.startswith(f"{name} ") for p in report.problems), report.problems
    assert all(value not in p for p in report.problems)


def test_the_core_profile_doesnt_apply_the_hosted_secret_rules():
    """A laptop may use generated short values; the hosted rules are for the deploy profile only."""
    report = build_report("core", settings_from(core(LEDGER_API_TOKEN="ci-only-throwaway")))
    assert not any("default or test value" in p for p in report.problems)


def test_automation_profile_needs_n8n_switched_on():
    values = core() | {k: FAKE[k] for k in preflight._AUTOMATION}
    report = build_report("automation", settings_from(values))
    assert any("FEATURE_N8N=true" in p for p in report.problems)
    assert build_report("automation", settings_from(values | {"FEATURE_N8N": "true"})).ready


def test_stage9_and_observability_profiles_list_their_own_variables():
    assert {"STAGE9_API_URL", "STAGE9_API_TOKEN"} <= set(build_report("stage9-adapter", settings_from(core())).required)
    report = build_report("observability", settings_from(core()))
    assert report.required["GRAFANA_ADMIN_PASSWORD"] == "missing" and not report.ready


def test_app_profile_mismatch_is_reported():
    report = build_report("deploy", settings_from(core()))
    assert any("different profile" in p for p in report.problems)
    # Overlays accept the base profile.
    assert not any("different profile" in p for p in build_report("observability", settings_from(core())).problems)


def test_features_unlocked_and_blocked():
    report = build_report("core", settings_from(core()))
    assert report.features["Offline pipeline and investigator (mock AI, local Docker)"] == []
    assert report.features["Live Claude runs (arm C live; needs the owner's OK and a cap)"] == [
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_MODEL",
    ]


def test_unknown_names_are_listed_by_name_only(tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_text("ANTHROPC_API_KEY=sk-ant-typo-value-123456789\n", encoding="utf-8")
    main(["--env-file", str(env)], environ={})
    out = capsys.readouterr().out
    assert "ANTHROPC_API_KEY" in out
    assert "sk-ant-typo-value" not in out


def test_json_output_shape(tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_text("".join(f"{k}={v}\n" for k, v in core().items()), encoding="utf-8")
    code = main(["--profile", "core", "--env-file", str(env), "--json"], environ={})
    data = json.loads(capsys.readouterr().out)
    assert code == 0 and data["ready"] is True
    assert data["required"]["APP_SECRET_KEY"] == "set"
    assert data["sources"]["APP_SECRET_KEY"] == ".env"


def test_missing_env_file_is_not_ready(tmp_path, capsys):
    code = main(["--profile", "core", "--env-file", str(tmp_path / "absent.env")], environ={})
    assert code == 1
    assert "NOT READY" in capsys.readouterr().out


def test_usage_error_exits_2():
    with pytest.raises(SystemExit) as exc:
        main(["--profile", "nope"], environ={})
    assert exc.value.code == 2
