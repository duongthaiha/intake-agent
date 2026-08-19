# scripts/azure/preflight.ps1 — Windows PowerShell version of preflight.sh
# Run via azd preprovision hook on Windows.
param(
  [string]$SubscriptionId = $env:AZURE_SUBSCRIPTION_ID,
  [string]$Location = ($env:AZURE_LOCATION ?? "eastus2"),
  [string]$EnvName = ($env:AZURE_ENV_NAME ?? "dev"),
  [string]$PrincipalId = $env:AZURE_PRINCIPAL_ID,
  [string]$ResourceGroup = ($env:AZURE_RESOURCE_GROUP ?? "rg-intake-$($env:AZURE_ENV_NAME ?? 'dev')")
)

$ErrorActionPreference = "Continue"
$errors = 0
$warnings = 0

function Write-Info  { param($msg) Write-Host "  ✅ $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "  ⚠️  $msg" -ForegroundColor Yellow; $script:warnings++ }
function Write-Fail  { param($msg) Write-Host "  ❌ $msg" -ForegroundColor Red; $script:errors++ }
function Write-Sect  { param($msg) Write-Host "`n━━━ $msg ━━━" -ForegroundColor Cyan }

Write-Sect "1. Subscription"
if (-not $SubscriptionId) {
  $SubscriptionId = az account show --query id -o tsv 2>$null
}
if (-not $SubscriptionId) {
  Write-Fail "No subscription. Run 'az login' and set AZURE_SUBSCRIPTION_ID."
  exit 1
}
$subState = az account show --subscription $SubscriptionId --query state -o tsv 2>$null
if ($subState -eq "Enabled") {
  Write-Info "Subscription $SubscriptionId is Enabled"
} else {
  Write-Fail "Subscription state: $subState"
}

Write-Sect "2. Provider Registrations"
# Foundry is provisioned unconditionally by infra/main.bicep (the dead
# deployFoundry toggle is gone), so its providers are hard requirements, not
# warnings. Only the Bot Service remains genuinely optional.
$required = @{
  "Microsoft.Storage" = "required"
  "Microsoft.DocumentDB" = "required"
  "Microsoft.ServiceBus" = "required"
  "Microsoft.Search" = "required"
  "Microsoft.KeyVault" = "required"
  "Microsoft.Web" = "required"
  "Microsoft.App" = "required"
  "Microsoft.Network" = "required"
  "Microsoft.ManagedIdentity" = "required"
  "Microsoft.OperationalInsights" = "required"
  "microsoft.insights" = "required"
  "Microsoft.MachineLearningServices" = "required-foundry"
  "Microsoft.CognitiveServices" = "required-foundry"
  "Microsoft.BotService" = "optional-bot"
}
foreach ($kv in $required.GetEnumerator()) {
  $state = az provider show --namespace $kv.Key --subscription $SubscriptionId `
    --query registrationState -o tsv 2>$null
  if ($state -eq "Registered") {
    Write-Info "$($kv.Key): Registered"
  } elseif ($kv.Value -eq "required") {
    Write-Fail "$($kv.Key): $state — register with: az provider register --namespace $($kv.Key)"
  } elseif ($kv.Value -eq "required-foundry") {
    Write-Fail "$($kv.Key): $state — Foundry is deployed unconditionally; register with: az provider register --namespace $($kv.Key)"
  } else {
    Write-Warn "$($kv.Key): $state — required when deployBotService=true"
  }
}

# The deployment needs two distinct capabilities at the target resource group:
#   1. Contributor — to create/update the resources themselves.
#   2. Authority to WRITE role assignments — main.bicep and the postprovision
#      RBAC reconciliation both create Microsoft.Authorization/roleAssignments.
#      Contributor explicitly cannot do this, so a deployment with Contributor
#      alone fails partway through, after resources exist. Any one of Role
#      Based Access Control Administrator, User Access Administrator, or Owner
#      satisfies it.
Write-Sect "3. RBAC"
if (-not $PrincipalId) {
  Write-Fail "AZURE_PRINCIPAL_ID is required (federated service principal object ID)"
} else {
  Write-Info "Deploying service principal: $PrincipalId"
  # Includes inherited subscription/management-group assignments, which are
  # just as effective at the resource-group scope.
  $assigned = @(az role assignment list --assignee-object-id $PrincipalId `
    --scope "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup" --include-inherited `
    --query "[].roleDefinitionName" -o tsv 2>$null)

  if (($assigned -contains "Contributor") -or ($assigned -contains "Owner")) {
    Write-Info "Contributor-equivalent role found at $ResourceGroup"
  } else {
    Write-Fail "Contributor role not found at $ResourceGroup for supplied service principal"
  }

  $roleWriteRoles = @("Role Based Access Control Administrator", "User Access Administrator", "Owner")
  $roleWriteFound = $roleWriteRoles | Where-Object { $assigned -contains $_ } | Select-Object -First 1
  if ($roleWriteFound) {
    Write-Info "Role-assignment authority found at ${ResourceGroup}: $roleWriteFound"
  } else {
    Write-Fail "No role-assignment authority at $ResourceGroup — the deployment creates role assignments and needs one of: $($roleWriteRoles -join ', ')"
  }
}

Write-Sect "4. Summary"
Write-Host "  Errors:   $errors"
Write-Host "  Warnings: $warnings"
if ($errors -gt 0) {
  Write-Host "`n❌ Preflight FAILED" -ForegroundColor Red
  exit 1
} else {
  Write-Host "`n✅ Preflight PASSED" -ForegroundColor Green
  exit 0
}
