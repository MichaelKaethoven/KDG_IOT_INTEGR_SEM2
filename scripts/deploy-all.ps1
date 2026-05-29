# Deploy the project's Fly.io apps: middleware (+subscriber), webapp, grafana.
#
# The target app name for each deploy comes from the `app =` line inside its own
# fly config, so this script never duplicates (and can't drift from) the names in
# the toml files. Deploys always run middleware -> webapp -> grafana.
#
# Usage:
#   .\scripts\deploy-all.ps1                       # deploy all three, in order
#   .\scripts\deploy-all.ps1 -Apps webapp          # deploy just one
#   .\scripts\deploy-all.ps1 -Apps middleware,grafana
#
# Requires: flyctl installed and authenticated (run `flyctl auth login` first).

[CmdletBinding()]
param(
    [ValidateSet("middleware", "webapp", "grafana")]
    [string[]]$Apps = @("middleware", "webapp", "grafana")
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path "$PSScriptRoot\.."

# Friendly name -> fly config. Ordered so middleware deploys before the webapp
# that calls it; iterating these keys also fixes deploy order regardless of the
# order -Apps is passed in.
$configs = [ordered]@{
    middleware = "fly.toml"
    webapp     = "fly.webapp.toml"
    grafana    = "fly.grafana.toml"
}

if (-not (Get-Command flyctl -ErrorAction SilentlyContinue)) {
    throw "flyctl not found on PATH. Install it from https://fly.io/docs/flyctl/install/ and run 'flyctl auth login'."
}

Push-Location $repoRoot
try {
    foreach ($name in $configs.Keys) {
        if ($Apps -notcontains $name) { continue }
        $config = $configs[$name]
        if (-not (Test-Path $config)) { throw "Config not found: $config" }

        Write-Host "`n=== Deploying $name ($config) ===" -ForegroundColor Cyan
        flyctl deploy --config $config
        if ($LASTEXITCODE -ne 0) { throw "Deploy failed for $name (flyctl exit $LASTEXITCODE)." }
    }
    Write-Host "`nAll requested deploys completed." -ForegroundColor Green
}
finally {
    Pop-Location
}
