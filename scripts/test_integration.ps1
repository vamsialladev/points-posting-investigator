# Real-Postgres and real-Kafka tests against the running local stack (start it first: scripts\stack.ps1 up).
# A skipped or missing infrastructure test fails the run (REQUIRE_MARKERS=postgres,kafka; standing rule 7).
# No value from .env is printed. Extra arguments go to pytest, for example: scripts\test_integration.ps1 -k ledger
# Usage (from the repository root):  powershell -ExecutionPolicy Bypass -File scripts\test_integration.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
uv run python scripts\run_integration.py @args
exit $LASTEXITCODE
