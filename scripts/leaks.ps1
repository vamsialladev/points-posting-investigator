# Looks for .env secret values inside Git-tracked files; prints names only, never values. Same as `make leaks`.
# Exit 0 = checked and clean, 1 = leak found, 3 = NOT RUN (nothing to check: no .env or no secrets in it).
Set-Location (Split-Path -Parent $PSScriptRoot)
uv run python -m app.env_leaks
exit $LASTEXITCODE
