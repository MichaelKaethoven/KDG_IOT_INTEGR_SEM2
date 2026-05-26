# Pin Dockerfile base images to specific @sha256 digests.
# Run after starting Docker Desktop. Replaces "FROM python:3.11-slim" and
# "FROM grafana/grafana:11.0.0" with their currently-resolved digests.

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path "$PSScriptRoot\.."

function Get-Digest {
    param([string]$Image)
    docker pull $Image | Out-Null
    $digest = (docker inspect $Image --format '{{index .RepoDigests 0}}').Split('@')[1]
    if (-not $digest) { throw "Could not resolve digest for $Image" }
    return $digest
}

$pyDigest = Get-Digest "python:3.11-slim"
$grafanaDigest = Get-Digest "grafana/grafana:11.0.0"

Write-Host "python:3.11-slim     -> $pyDigest"
Write-Host "grafana/grafana:11.0 -> $grafanaDigest"

$dockerfiles = @(
    "$repoRoot\Dockerfile",
    "$repoRoot\Dockerfile.webapp"
)
foreach ($f in $dockerfiles) {
    (Get-Content $f) -replace 'FROM python:3.11-slim(@sha256:[a-f0-9]+)?', "FROM python:3.11-slim@$pyDigest" `
        | Set-Content -Encoding utf8 $f
}
(Get-Content "$repoRoot\Dockerfile.grafana") `
    -replace 'FROM grafana/grafana:11.0.0(@sha256:[a-f0-9]+)?', "FROM grafana/grafana:11.0.0@$grafanaDigest" `
    | Set-Content -Encoding utf8 "$repoRoot\Dockerfile.grafana"

Write-Host "Done. Review the diff and commit."
