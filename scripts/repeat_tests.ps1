# Run each named infrastructure test N times against the running stack, and tally passes and failures.
# Flaky timing shows up here, not in a single run (M2: the ledger race test passed once and failed in CI).
# Usage (from the repository root, stack running, machine quiet: scripts\quiet_check.ps1 first):
#   powershell -ExecutionPolicy Bypass -File scripts\repeat_tests.ps1 -Tests two_workers,crash_after_parking -Times 10 -Out docs\evidence\runs.md
#
# Evidence (lessons from M2 PR-B1 and PR-B2b):
#   - one line per test (pytest -vv; -v alone is cancelled by addopts' -q), unbuffered, with faulthandler: a slow or dying run never looks empty
#   - the full output of EVERY run is kept in .test-logs\<batch>\ (git-ignored); runs that don't pass are also copied
#     next to -Out as <Out>.<test>.run<N>.txt, so they can be committed
#   - every run's exit code is in its log
#   - CPU is sampled every 5 s. A run whose mean CPU is above -CpuFlagPercent is FLAGGED (the machine was busy, so its
#     result says little), its log kept, and it is run again (up to -MaxReruns times). Flagged runs are not counted; a run still
#     flagged after the last re-run is "still flagged", not counted, and the batch fails (it can't be N/N).
# No value from .env is printed.
param(
    [Parameter(Mandatory = $true)][string[]]$Tests,
    [int]$Times = 10,
    [string]$Out = "",
    [int]$CpuFlagPercent = 60,
    [int]$MaxReruns = 3
)
$Tests = @($Tests | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
function FullPath([string]$path) { if ([System.IO.Path]::IsPathRooted($path)) { $path } else { Join-Path $PWD $path } }
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)
$utf8 = New-Object System.Text.UTF8Encoding $false
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONFAULTHANDLER = "1"
$batch = (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmss")
$logDir = Join-Path ".test-logs" $batch
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
if ($Out) { New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Out) | Out-Null }

# CPU sampler: one "<unix seconds>,<percent>" line every 5 s, for the whole batch.
$cpuFile = Join-Path (Resolve-Path $logDir) "cpu.csv"
$sampler = Start-Job -ScriptBlock {
    param($path)
    while ($true) {
        $value = (Get-Counter '\Processor(_Total)\% Processor Time' -SampleInterval 5 -MaxSamples 1).CounterSamples[0].CookedValue
        Add-Content -Path $path -Value ("{0},{1:N1}" -f [DateTimeOffset]::UtcNow.ToUnixTimeSeconds(), $value)
    }
} -ArgumentList $cpuFile

function MeanCpu([long]$from, [long]$to) {
    if (-not (Test-Path $cpuFile)) { return $null }
    $values = @(Get-Content $cpuFile | ForEach-Object { $t, $v = $_ -split ","; if ([long]$t -ge $from -and [long]$t -le $to) { [double]$v } })
    if ($values.Count -eq 0) { return $null }
    return [math]::Round(($values | Measure-Object -Average).Average, 1)
}

$rows = New-Object System.Collections.Generic.List[object]
$notes = New-Object System.Collections.Generic.List[string]
try {
    foreach ($test in $Tests) {
        $passed = 0; $failed = 0; $other = 0; $flagged = 0; $unresolved = 0
        $seconds = New-Object System.Collections.Generic.List[double]
        $cpus = New-Object System.Collections.Generic.List[double]
        $safe = $test -replace '[^\w]', '_'
        foreach ($i in 1..$Times) {
            $attempt = 0
            while ($true) {
                $attempt++
                $start = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
                $watch = [System.Diagnostics.Stopwatch]::StartNew()
                # -vv: pyproject's addopts already has -q, and -q -v cancel out to one line per FILE.
                $output = @(uv run python scripts\run_integration.py -k $test -s -vv 2>&1 | ForEach-Object { "$_" })
                $exitCode = $LASTEXITCODE
                $watch.Stop()
                $cpu = MeanCpu $start ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())
                $output += "repeat_tests: exit code $exitCode after $([int]$watch.Elapsed.TotalSeconds) s; mean CPU $cpu %"
                $log = Join-Path $logDir "$safe.run$i.try$attempt.log"
                [System.IO.File]::WriteAllLines((FullPath $log), $output, $utf8)
                $summary = ($output | Select-String -Pattern "^\d+ (passed|failed)|^=+ .*(passed|failed)" | Select-Object -Last 1)
                $line = if ($summary) { $summary.Line } else { "" }
                $busy = ($null -ne $cpu) -and ($cpu -gt $CpuFlagPercent)
                if ($busy -and $attempt -le $MaxReruns) {
                    $flagged++
                    Write-Host "  run $i of '$test' FLAGGED (mean CPU $cpu % > $CpuFlagPercent %): not counted, running it again"
                    $notes.Add("``$test`` run $i try ${attempt}: flagged, mean CPU $cpu %, not counted (log ``$log``)")
                    continue
                }
                break
            }
            if ($busy) {
                # Still busy after every re-run: the result is not counted either way, and the batch can't be 10/10.
                $unresolved++
                Write-Host "  run $i of '$test' still FLAGGED after $MaxReruns re-runs (mean CPU $cpu %): not counted"
                $notes.Add("``$test`` run ${i}: still flagged after $MaxReruns re-runs (mean CPU $cpu %), not counted (log ``$log``)")
                continue
            }
            $seconds.Add($watch.Elapsed.TotalSeconds)
            if ($null -ne $cpu) { $cpus.Add($cpu) }
            foreach ($e in ($output | Select-String -Pattern "^evidence:|evidence: ")) {
                $text = $e.Line.Substring($e.Line.IndexOf("evidence:") + 9).Trim()
                $notes.Add("``$test`` run ${i}: $text")
            }
            if ($line -match "\b1 passed" -and $line -notmatch "failed|error") { $passed++; continue }
            if ($line -match "failed|error") { $failed++; Write-Host "  run $i of '$test' FAILED: $line (exit $exitCode)" }
            else { $other++; Write-Host "  run $i of '$test': no single-test summary (exit $exitCode)" }
            if ($Out) {
                $copy = "$Out.$safe.run$i.txt"
                Copy-Item $log $copy
                Write-Host "  saved to $copy"
            }
        }
        $rows.Add([pscustomobject]@{
            Test = $test; Runs = $Times; Passed = $passed; Failed = $failed; NotOneTest = $other; Flagged = $flagged; Unresolved = $unresolved
            MeanSeconds = [math]::Round((($seconds | Measure-Object -Average).Average), 1)
            MaxSeconds = [math]::Round((($seconds | Measure-Object -Maximum).Maximum), 1)
            MeanCpu = if ($cpus.Count) { [math]::Round((($cpus | Measure-Object -Average).Average), 1) } else { "n/a" }
        })
    }
} finally {
    Stop-Job $sampler -ErrorAction SilentlyContinue
    Remove-Job $sampler -Force -ErrorAction SilentlyContinue
}
Write-Host ($rows | Format-Table -AutoSize | Out-String -Width 220)
if ($Out) {
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm") + " UTC"
    $commit = (git rev-parse --short HEAD)
    $dirty = if (git status --porcelain) { " plus uncommitted changes" } else { "" }
    $md = @(
        "# Repeat runs", "",
        "Generated by ``scripts\repeat_tests.ps1`` on $stamp, at commit ``$commit``$dirty.",
        "Each run is one ``pytest -k <test> -vv`` against the local stack (``REQUIRE_MARKERS=postgres,kafka``).",
        "A run with mean CPU above $CpuFlagPercent % is flagged, not counted, and run again (up to $MaxReruns times).",
        "Full logs of every run: ``$logDir`` (local, git-ignored); runs that didn't pass are copied next to this file.", "",
        "| Test | Runs | Passed | Failed | Not one test | Flagged (re-run) | Still flagged (not counted) | Mean s | Max s | Mean CPU % |",
        "|---|---|---|---|---|---|---|---|---|---|"
    )
    foreach ($r in $rows) { $md += "| ``$($r.Test)`` | $($r.Runs) | $($r.Passed) | $($r.Failed) | $($r.NotOneTest) | $($r.Flagged) | $($r.Unresolved) | $($r.MeanSeconds) | $($r.MaxSeconds) | $($r.MeanCpu) |" }
    if ($notes.Count -gt 0) { $md += ""; $md += "Notes and measurements:"; $md += ""; foreach ($n in $notes) { $md += "- $n" } }
    [System.IO.File]::WriteAllLines((FullPath $Out), $md, $utf8)
    Write-Host "Saved to $Out"
}
$bad = @($rows | Where-Object { $_.Passed -ne $_.Runs })
if ($bad.Count -gt 0) { exit 1 }
exit 0
