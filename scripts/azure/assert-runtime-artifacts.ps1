[CmdletBinding()]
param(
  [switch]$AllowDisabled
)

$ErrorActionPreference = 'Stop'

$requiredImages = @()
if ($env:AZURE_DEPLOY_WORKLOADS -eq 'true') {
  $requiredImages += 'COMMAND_SERVICE_IMAGE'
}
if ($env:AZURE_DEPLOY_WORKERS -eq 'true') {
  $requiredImages += 'WORKERS_IMAGE'
}
if ($env:AZURE_DEPLOY_EVALUATION -eq 'true') {
  $requiredImages += 'EVALUATION_IMAGE'
}
if ($env:AZURE_DEPLOY_FOUNDRY_CONFIGURATION -eq 'true') {
  $requiredImages += 'FOUNDRY_CONFIGURATION_IMAGE'
}

if ($requiredImages.Count -eq 0) {
  if ($AllowDisabled) {
    Write-Host 'Runtime deployment is disabled; artifact checks are not required for infrastructure-only provisioning.'
    exit 0
  }
  throw 'Runtime deployment is disabled. Enable a workload only after its immutable image and Foundry artifacts are available.'
}

foreach ($variableName in $requiredImages) {
  $value = [Environment]::GetEnvironmentVariable($variableName)
  if ([string]::IsNullOrWhiteSpace($value) -or $value -eq 'runtime-artifact-required' -or $value -notmatch '@sha256:[a-fA-F0-9]{64}$') {
    throw "$variableName must be an immutable container image digest before azd deploy."
  }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$manifestPath = Join-Path $repoRoot 'infra\foundry\deployables.json'
$manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json -Depth 20
$missingArtifacts = @()
foreach ($deployable in $manifest.deployables) {
  if ($deployable.required -and -not (Test-Path (Join-Path $repoRoot $deployable.artifactPath))) {
    $missingArtifacts += "$($deployable.name): $($deployable.artifactPath)"
  }
}
if ($missingArtifacts.Count -gt 0) {
  throw "Required Foundry artifacts are missing: $($missingArtifacts -join '; ')."
}

Write-Host 'Runtime image gate passed.'
