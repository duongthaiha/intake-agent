[CmdletBinding()]
param(
  [string]$EnvironmentName = $(if ($env:AZURE_ENV_NAME) { $env:AZURE_ENV_NAME } else { 'dev' }),
  [string]$Location = $(if ($env:AZURE_LOCATION) { $env:AZURE_LOCATION } else { 'eastus2' }),
  [string]$SubscriptionId = $env:AZURE_SUBSCRIPTION_ID,
  [switch]$StaticOnly,
  [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$parameterFile = Join-Path $repoRoot "infra\main.$EnvironmentName.bicepparam"

& (Join-Path $PSScriptRoot 'assert-runtime-artifacts.ps1') -AllowDisabled
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

& (Join-Path $PSScriptRoot 'validate-infrastructure.ps1')
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

if ($StaticOnly) {
  Write-Host 'Static-only preflight passed.'
  exit 0
}

if (-not $SubscriptionId) {
  $SubscriptionId = az account show --query id --output tsv 2>$null
}
if (-not $SubscriptionId) {
  throw 'No Azure subscription is selected. Run az login and set AZURE_SUBSCRIPTION_ID.'
}

az account set --subscription $SubscriptionId
if ($LASTEXITCODE -ne 0) {
  throw "Unable to select subscription '$SubscriptionId'."
}

$requiredProviders = @(
  'Microsoft.App',
  'Microsoft.Authorization',
  'Microsoft.CognitiveServices',
  'Microsoft.Consumption',
  'Microsoft.ContainerRegistry',
  'Microsoft.DocumentDB',
  'Microsoft.Insights',
  'Microsoft.KeyVault',
  'Microsoft.ManagedIdentity',
  'Microsoft.Network',
  'Microsoft.OperationalInsights',
  'Microsoft.Search',
  'Microsoft.ServiceBus',
  'Microsoft.Storage'
)

$unregistered = @()
foreach ($provider in $requiredProviders) {
  $state = az provider show --namespace $provider --query registrationState --output tsv 2>$null
  if ($state -ne 'Registered') {
    $unregistered += "$provider ($state)"
  }
}
if ($unregistered.Count -gt 0) {
  throw "Required resource providers are not registered: $($unregistered -join ', ')."
}

if (-not (Test-Path $parameterFile)) {
  throw "No governed parameter file exists for environment '$EnvironmentName'."
}

$templateFile = Join-Path $repoRoot 'infra\main.bicep'
az deployment sub validate `
  --location $Location `
  --template-file $templateFile `
  --parameters $parameterFile `
  --only-show-errors | Out-Null
if ($LASTEXITCODE -ne 0) {
  throw 'Azure subscription-scope deployment validation failed.'
}

if ($WhatIf) {
  $whatIfSucceeded = $false
  foreach ($attempt in 1..3) {
    az deployment sub what-if `
      --location $Location `
      --template-file $templateFile `
      --parameters $parameterFile `
      --result-format ResourceIdOnly `
      --only-show-errors
    if ($LASTEXITCODE -eq 0) {
      $whatIfSucceeded = $true
      break
    }
    if ($attempt -lt 3) {
      Write-Warning "Azure what-if attempt $attempt failed; retrying after $($attempt * 10) seconds."
      Start-Sleep -Seconds ($attempt * 10)
    }
  }
  if (-not $whatIfSucceeded) {
    throw 'Azure subscription-scope what-if failed after three attempts.'
  }
}

Write-Host 'Online deployment preflight passed. No resources were deployed.'
