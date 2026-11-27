# Show, trigger or reset one of the 18 pre-registered failure scenarios on the LOCAL stack (synthetic data, $0).
# Same as `make scenario ARGS="..."`. The stack must be up for trigger and reset: scripts\stack.ps1 up
# Usage (from the repository root):
#   powershell -ExecutionPolicy Bypass -File scripts\scenario.ps1 list
#   powershell -ExecutionPolicy Bypass -File scripts\scenario.ps1 plan S05 -Run 3        # read-only
#   powershell -ExecutionPolicy Bypass -File scripts\scenario.ps1 trigger S05 -Run 3     # breaks the stack on purpose
#   powershell -ExecutionPolicy Bypass -File scripts\scenario.ps1 reset S05 -Run 3
#   powershell -ExecutionPolicy Bypass -File scripts\scenario.ps1 trigger S15 -Pair A
# It refuses any address that isn't this machine. No value from .env is printed.
param(
    [Parameter(Mandatory = $true, Position = 0)][ValidateSet("list", "plan", "trigger", "reset")][string]$Action,
    [Parameter(Position = 1)][string]$Scenario,
    [int]$Run = 0,
    [ValidateSet("", "A", "B")][string]$Pair = ""
)
Set-Location (Split-Path -Parent $PSScriptRoot)
if ($Action -eq "list") { uv run python -m app.scenarios list; exit $LASTEXITCODE }
if (-not $Scenario) { Write-Host "Give a scenario, for example: scripts\scenario.ps1 $Action S05"; exit 2 }
$arguments = @($Action, $Scenario, "--run", $Run)
if ($Pair) { $arguments += @("--pair", $Pair) }
uv run python -m app.scenarios @arguments
exit $LASTEXITCODE
