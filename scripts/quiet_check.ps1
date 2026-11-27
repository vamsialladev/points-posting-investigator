# Is the machine quiet enough for a repeat batch? Samples total CPU every 5 s for -Minutes, and lists the busiest
# processes at the end. Passes (exit 0) only if every sample is under -MaxPercent and the mean is under -MeanPercent.
# With -Out, the samples and the verdict are saved (a stored result, standing rule 3).
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\quiet_check.ps1 -Minutes 5 -Out docs\evidence\quiet-check.md
param([int]$Minutes = 5, [int]$MaxPercent = 50, [int]$MeanPercent = 25, [string]$Out = "")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$samples = [int]($Minutes * 60 / 5)
$started = (Get-Date).ToUniversalTime()
$values = @((Get-Counter '\Processor(_Total)\% Processor Time' -SampleInterval 5 -MaxSamples $samples).CounterSamples |
    ForEach-Object { [math]::Round($_.CookedValue, 1) })
$mean = [math]::Round(($values | Measure-Object -Average).Average, 1)
$max = [math]::Round(($values | Measure-Object -Maximum).Maximum, 1)
$quiet = ($max -lt $MaxPercent) -and ($mean -lt $MeanPercent)
$top = Get-Process | Sort-Object CPU -Descending | Select-Object -First 8 Name, Id, @{n = 'cpu_s'; e = { [int]$_.CPU } }
$pythons = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ForEach-Object { $_.CommandLine.Substring(0, [Math]::Min(100, $_.CommandLine.Length)) })
$verdict = if ($quiet) { "QUIET" } else { "BUSY" }
Write-Host "$verdict over $Minutes min ($($values.Count) samples): mean $mean %, max $max % (limits: mean < $MeanPercent %, every sample < $MaxPercent %)"
Write-Host "Python processes running: $($pythons.Count)"
if ($Out) {
    $md = @(
        "# Quiet check", "",
        "``scripts\quiet_check.ps1`` from $($started.ToString('yyyy-MM-dd HH:mm')) UTC, $Minutes minutes, one sample every 5 s.", "",
        "**$verdict**: mean $mean %, max $max % (limits: mean < $MeanPercent %, every sample < $MaxPercent %).", "",
        "Samples (%): " + ($values -join ", "), "",
        "Busiest processes at the end (cumulative CPU seconds): " + (($top | ForEach-Object { "$($_.Name) $($_.cpu_s)" }) -join "; "), "",
        "Python processes running: $($pythons.Count)"
    )
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Out) | Out-Null
    $target = if ([System.IO.Path]::IsPathRooted($Out)) { $Out } else { Join-Path $PWD $Out }
    [System.IO.File]::WriteAllLines($target, $md, (New-Object System.Text.UTF8Encoding $false))
}
if ($quiet) { exit 0 } else { exit 1 }
