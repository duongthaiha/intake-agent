[CmdletBinding()]
param(
  [string]$ManifestPath = $(Join-Path $PSScriptRoot '..\..\infra\foundry\deployables.json')
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

if ($env:AZURE_DEPLOY_WORKLOADS -ne 'true') {
  Write-Host 'Foundry deployables are intentionally deferred because runtime deployment is disabled.'
  exit 0
}

$manifest = Get-Content -Raw $ManifestPath | ConvertFrom-Json -Depth 20
$missingArtifacts = @()
foreach ($deployable in $manifest.deployables) {
  if (-not $deployable.required) {
    continue
  }
  $artifactPath = Join-Path $repoRoot $deployable.artifactPath
  if (-not (Test-Path $artifactPath)) {
    $missingArtifacts += "$($deployable.name): $($deployable.artifactPath)"
  }
}

if ($missingArtifacts.Count -gt 0) {
  throw "Foundry configuration is blocked until required artifacts exist: $($missingArtifacts -join '; ')."
}

if (-not $env:AZURE_FOUNDRY_PROJECT_ID) {
  throw 'AZURE_FOUNDRY_PROJECT_ID is required for Foundry configuration.'
}

Write-Host 'Foundry artifacts are present. Deploy each governed manifest entry with its declared provisioner, then run post-publish-rbac.ps1 against the actual instance identities.'
