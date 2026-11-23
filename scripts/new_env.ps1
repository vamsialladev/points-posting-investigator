# Creates .env from .env.example and fills the local-only secrets with random values, printing no value.
# Refuses to overwrite an existing .env. Live keys (ANTHROPIC_API_KEY, SLACK_WEBHOOK_URL, STAGE9_API_TOKEN) are
# left empty: you type those into .env yourself, only when a milestone needs them and you've approved it.
# Usage (from the repository root):
#   powershell -ExecutionPolicy Bypass -File scripts\new_env.ps1               # a new .env
#   powershell -ExecutionPolicy Bypass -File scripts\new_env.ps1 -AddMissing   # an existing .env: fill only the
#                                                                              # generated names that are empty or
#                                                                              # absent; every other line is kept
param([switch]$AddMissing)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function New-Secret([int]$bytes) {
    $buffer = New-Object byte[] $bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    # URL-safe characters only, so the value can sit inside DATABASE_URL.
    return ([Convert]::ToBase64String($buffer)).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

$generated = [ordered]@{
    "APP_SECRET_KEY"            = 48
    "POSTGRES_PASSWORD"         = 24
    "LEDGER_DB_PASSWORD"        = 24
    "POSTING_DB_PASSWORD"       = 24
    "RELAY_DB_PASSWORD"         = 24
    "LEDGER_API_TOKEN"          = 24
    "GRAFANA_ADMIN_PASSWORD"    = 24
    "AUTOMATION_WEBHOOK_SECRET" = 48
    "N8N_ENCRYPTION_KEY"        = 36
}
# UTF-8 without a byte-order mark, so python-dotenv and Docker Compose read the first name correctly.
$utf8 = New-Object System.Text.UTF8Encoding $false
$target = Join-Path $PWD ".env"

if (Test-Path .env) {
    if (-not $AddMissing) { Write-Host ".env already exists: left unchanged. (-AddMissing fills only empty or absent names.)"; exit 1 }
    $existing = @(Get-Content .env -Encoding UTF8)
    $added = New-Object System.Collections.Generic.List[string]
    $lines = foreach ($line in $existing) {
        $out = $line
        foreach ($name in $generated.Keys) {
            if ($line -eq "$name=") { $out = "$name=" + (New-Secret $generated[$name]); $added.Add($name) }
        }
        $out
    }
    $lines = @($lines)
    foreach ($name in $generated.Keys) {
        $present = @($lines | Where-Object { $_ -like "$name=*" }).Count -gt 0
        if (-not $present) { $lines += "$name=" + (New-Secret $generated[$name]); $added.Add($name) }
    }
    if ($added.Count -eq 0) { Write-Host "Nothing to add: every generated name already has a value. .env unchanged."; exit 0 }
    [System.IO.File]::WriteAllLines($target, $lines, $utf8)
    Write-Host ("Added {0} generated local value(s) to .env: {1}" -f $added.Count, (($added | Sort-Object) -join ", "))
    Write-Host "Existing values were kept. No value was printed. Check it with: scripts\preflight.ps1 -Profile core"
    exit 0
}

$lines = Get-Content .env.example -Encoding UTF8 | ForEach-Object {
    $line = $_
    foreach ($name in $generated.Keys) {
        if ($line -eq "$name=") { $line = "$name=" + (New-Secret $generated[$name]) }
    }
    $line
}
[System.IO.File]::WriteAllLines($target, $lines, $utf8)
Write-Host ("Created .env with {0} generated local value(s): {1}" -f $generated.Count, (($generated.Keys | Sort-Object) -join ", "))
Write-Host "No value was printed. Check it with: scripts\preflight.ps1 -Profile core"
