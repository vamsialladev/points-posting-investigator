# The CI pipeline, run on this machine with the same pinned tools (Stage 9's scripts\ci_local.ps1 pattern).
# The same jobs as .github/workflows/ci.yml: checks (with the audit), integration (real Kafka, Karapace and Postgres
# from the core compose stack), migrations (in separate ci_ databases, so the stack's data is untouched) and secrets.
# Later milestones add the browser job (M8) and the image/SBOM/link jobs (M13 slice).
# Usage (from the repo root):
#   powershell -ExecutionPolicy Bypass -File scripts\ci_local.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\ci_local.ps1 -Skip secrets
#   powershell -ExecutionPolicy Bypass -File scripts\ci_local.ps1 -Skip integration,migrations   # without Docker
param([string[]]$Skip = @())
$Skip = @($Skip | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$ErrorActionPreference = "Continue"  # Docker writes progress to stderr; exit codes are checked
Set-Location (Split-Path -Parent $PSScriptRoot)
$results = New-Object System.Collections.Generic.List[object]

function Step([string]$job, [string]$name, [scriptblock]$block) {
    Write-Host "== [$job] $name"
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $global:LASTEXITCODE = 0
    & $block
    $code = $LASTEXITCODE
    $watch.Stop()
    $results.Add([pscustomobject]@{ Job = $job; Step = $name; Result = $(if ($code -eq 0) { "pass" } else { "FAIL ($code)" }); Seconds = [int]$watch.Elapsed.TotalSeconds })
    if ($code -ne 0) { Write-Host "FAILED: [$job] $name" }
}

if ($Skip -notcontains "checks") {
    Step "checks" "uv sync --frozen" { uv sync --frozen }
    Step "checks" "ruff check" { uv run ruff check . }
    Step "checks" "ruff format --check" { uv run ruff format --check . }
    Step "checks" "mypy" { uv run mypy }
    Step "checks" "tests with the coverage gate" { uv run pytest --cov --cov-report=term-missing -rs -p no:cacheprovider }
    Step "checks" "known vulnerabilities in the locked dependencies" {
        $req = Join-Path $env:TEMP "ppi-ci-local-requirements-audit.txt"
        uv export --frozen --no-hashes --no-emit-project --all-groups -o $req -q
        uvx pip-audit==2.10.1 -r $req --no-deps --disable-pip
        $code = $LASTEXITCODE
        Remove-Item $req -ErrorAction SilentlyContinue
        $global:LASTEXITCODE = $code
    }
}

if ($Skip -notcontains "integration") {
    Step "integration" "core stack up (compose --wait)" { powershell -ExecutionPolicy Bypass -File scripts\stack.ps1 up }
    Step "integration" "infrastructure tests (REQUIRE_MARKERS=postgres,kafka)" {
        powershell -ExecutionPolicy Bypass -File scripts\test_integration.ps1
    }
}

if ($Skip -notcontains "migrations") {
    # Reads DATABASE_URL and the runtime passwords from .env inside Python; nothing is printed.
    Step "migrations" "bootstrap ci_ roles and databases" { uv run python -m app.db.bootstrap --prefix ci_ --reset }
    Step "migrations" "upgrade, downgrade, upgrade, drift check" { uv run python -m app.db.migrate roundtrip --prefix ci_ }
}

if ($Skip -notcontains "secrets") {
    Step "secrets" "gitleaks over the full history (values redacted, >0 commits)" {
        powershell -ExecutionPolicy Bypass -File scripts\secrets_scan.ps1
    }
}

Write-Host ""
$results | Format-Table -AutoSize | Out-String -Width 200 | Write-Host
$failed = @($results | Where-Object { $_.Result -ne "pass" })
if ($results.Count -eq 0) { Write-Host "local CI FAILED: no step ran (everything skipped)"; exit 1 }
if ($failed.Count -gt 0) { Write-Host "local CI FAILED: $($failed.Count) step(s)"; exit 1 }
Write-Host "local CI passed."
exit 0
