[CmdletBinding()]
param(
  [switch]$AllowDisabled
)

$ErrorActionPreference = 'Stop'

if ($env:AZURE_DEPLOY_WORKLOADS -ne 'true') {
  if ($AllowDisabled) {
    Write-Host 'Runtime deployment is disabled; artifact checks are not required for infrastructure-only provisioning.'
    exit 0
  }
  throw 'Runtime deployment is disabled. Set AZURE_DEPLOY_WORKLOADS=true only after immutable runtime images and Foundry artifacts are available.'
}

foreach ($variableName in @('COMMAND_SERVICE_IMAGE', 'WORKERS_IMAGE', 'EVALUATION_IMAGE')) {
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
