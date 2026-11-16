# Every target has a PowerShell twin in scripts\ (make isn't installed on the owner's Windows machine).
.PHONY: install test lint typecheck preflight leaks secrets ci

PROFILE ?= core

install:            ## scripts: uv sync
	uv sync

test:               ## scripts\test.ps1
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run pytest --cov --cov-report=term-missing -rs

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy

preflight:          ## scripts\preflight.ps1 -Profile $(PROFILE)
	uv run python -m app.preflight --profile $(PROFILE)

leaks:              ## scripts\leaks.ps1
	uv run python -m app.env_leaks

secrets:            ## scripts\secrets_scan.ps1
	docker run --rm -v "$(CURDIR):/repo" ghcr.io/gitleaks/gitleaks:v8.30.1 git /repo --redact --no-banner

ci:                 ## scripts\ci_local.ps1
	pwsh -File scripts/ci_local.ps1
