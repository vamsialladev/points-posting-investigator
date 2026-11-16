# Creates .env from .env.example and fills the local-only secrets with random values, printing no value.
# Refuses to overwrite an existing .env. Live keys (ANTHROPIC_API_KEY, SLACK_WEBHOOK_URL, STAGE9_API_TOKEN) are
# left empty: you type those into .env yourself, only when a milestone needs them and you've approved it.
# Usage (from the repository root):  powershell -ExecutionPolicy Bypass -File scripts\new_env.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (Test-Path .env) { Write-Host ".env already exists: left unchanged."; exit 1 }

function New-Secret([int]$bytes) {
    $buffer = New-Object byte[] $bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    # URL-safe characters only, so the value can sit inside DATABASE_URL.
    return ([Convert]::ToBase64String($buffer)).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

$generated = @{
    "APP_SECRET_KEY"            = 48
    "POSTGRES_PASSWORD"         = 24
    "LEDGER_API_TOKEN"          = 24
    "GRAFANA_ADMIN_PASSWORD"    = 24
    "AUTOMATION_WEBHOOK_SECRET" = 48
    "N8N_ENCRYPTION_KEY"        = 36
}
$lines = Get-Content .env.example -Encoding UTF8 | ForEach-Object {
    $line = $_
    foreach ($name in $generated.Keys) {
        if ($line -eq "$name=") { $line = "$name=" + (New-Secret $generated[$name]) }
    }
    $line
}
# UTF-8 without a byte-order mark, so python-dotenv and Docker Compose read the first name correctly.
[System.IO.File]::WriteAllLines((Join-Path $PWD ".env"), $lines, (New-Object System.Text.UTF8Encoding $false))
Write-Host ("Created .env with {0} generated local value(s): {1}" -f $generated.Count, (($generated.Keys | Sort-Object) -join ", "))
Write-Host "No value was printed. Check it with: scripts\preflight.ps1 -Profile core"
