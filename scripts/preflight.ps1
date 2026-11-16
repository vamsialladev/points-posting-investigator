# Configuration readiness without printing any value. Same as `make preflight PROFILE=...`.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\preflight.ps1 -Profile core
param([string]$Profile = "core")
Set-Location (Split-Path -Parent $PSScriptRoot)
uv run python -m app.preflight --profile $Profile
exit $LASTEXITCODE
