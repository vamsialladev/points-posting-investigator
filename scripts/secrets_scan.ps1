# gitleaks over the full Git history, from the same pinned image as CI and pre-commit (nothing to install).
# Values are redacted. A scan that covers no commits is a failure, not a pass (standing rule 7).
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\secrets_scan.ps1
$ErrorActionPreference = "Continue"  # Docker writes progress to stderr; exit codes are checked below
Set-Location (Split-Path -Parent $PSScriptRoot)
$image = "ghcr.io/gitleaks/gitleaks:v8.30.1"
# gitleaks logs to stderr; "$_" turns PowerShell 5.1's error records back into plain lines (no NativeCommandError noise).
$output = & docker run --rm -v "${PWD}:/repo" $image git /repo --redact --no-banner --no-color 2>&1 | ForEach-Object { "$_" } | Out-String
$code = $LASTEXITCODE
Write-Host $output.Trim()
$match = [regex]::Match($output, "(\d+) commits scanned")
if (-not $match.Success) { Write-Host "FAILED: gitleaks did not report how many commits it scanned"; exit 1 }
if ([int]$match.Groups[1].Value -lt 1) { Write-Host "FAILED (NOT RUN): gitleaks scanned 0 commits"; exit 1 }
if ($code -ne 0) { Write-Host "FAILED: gitleaks exit $code"; exit $code }
Write-Host ("gitleaks: {0} commit(s) scanned, no leaks." -f $match.Groups[1].Value)
exit 0
