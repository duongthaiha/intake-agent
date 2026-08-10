# scripts/azure/preflight.ps1 — Windows PowerShell version of preflight.sh
# Run via azd preprovision hook on Windows.
param(
  [string]$SubscriptionId = $env:AZURE_SUBSCRIPTION_ID,
  [string]$Location = ($env:AZURE_LOCATION ?? "eastus2"),
  [string]$EnvName = ($env:AZURE_ENV_NAME ?? "dev")
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
  "Microsoft.MachineLearningServices" = "optional-foundry"
  "Microsoft.CognitiveServices" = "optional-foundry"
  "Microsoft.BotService" = "optional-bot"
}
foreach ($kv in $required.GetEnumerator()) {
  $state = az provider show --namespace $kv.Key --subscription $SubscriptionId `
    --query registrationState -o tsv 2>$null
  if ($state -eq "Registered") {
    Write-Info "$($kv.Key): Registered"
  } elseif ($kv.Value -eq "required") {
    Write-Fail "$($kv.Key): $state — register with: az provider register --namespace $($kv.Key)"
  } elseif ($kv.Value -eq "optional-foundry") {
    Write-Warn "$($kv.Key): $state — required when deployFoundry=true"
  } else {
    Write-Warn "$($kv.Key): $state — required when deployBotService=true"
  }
}

Write-Sect "3. RBAC"
$principalId = az ad signed-in-user show --query id -o tsv 2>$null
if ($principalId) {
  Write-Info "Deploying principal: $principalId"
  $ownerRole = az role assignment list --assignee $principalId --subscription $SubscriptionId --all `
    --query "[?roleDefinitionName=='Owner'].roleDefinitionName | [0]" -o tsv 2>$null
  if ($ownerRole) {
    Write-Info "Owner role found"
  } else {
    Write-Warn "Owner role not found at subscription scope — verify resource group level RBAC"
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
