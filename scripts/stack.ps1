# Start, stop or inspect the local stack (Docker Compose profile `core`). Local only, synthetic data, $0.
# Usage (from the repository root):
#   powershell -ExecutionPolicy Bypass -File scripts\stack.ps1 up       # build, start, wait until healthy
#   powershell -ExecutionPolicy Bypass -File scripts\stack.ps1 status
#   powershell -ExecutionPolicy Bypass -File scripts\stack.ps1 logs
#   powershell -ExecutionPolicy Bypass -File scripts\stack.ps1 down     # stop; data kept
#   powershell -ExecutionPolicy Bypass -File scripts\stack.ps1 reset    # stop and DELETE the local data volume
# Compose reads .env itself; this script never reads or prints it.
param([ValidateSet("up", "status", "logs", "down", "reset")][string]$Action = "up")
$ErrorActionPreference = "Continue"  # Docker writes progress to stderr; exit codes are checked
Set-Location (Split-Path -Parent $PSScriptRoot)
switch ($Action) {
    "up" { docker compose --profile core up -d --build --wait --wait-timeout 300 }
    "status" { docker compose --profile core ps -a }
    "logs" { docker compose --profile core logs --tail 200 }
    "down" { docker compose --profile core down }
    "reset" { docker compose --profile core down -v }
}
exit $LASTEXITCODE
