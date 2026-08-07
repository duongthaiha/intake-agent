# scripts/azure/post-deploy-verify.ps1 — Windows PowerShell version
param(
  [string]$EnvName = ($env:AZURE_ENV_NAME ?? "dev"),
  [string]$SubscriptionId = $env:AZURE_SUBSCRIPTION_ID
)

$pass = 0; $fail = 0
$RgName = "rg-intake-$EnvName"

function Pass  { param($msg) Write-Host "  ✅ $msg" -ForegroundColor Green; $script:pass++ }
function Fail  { param($msg) Write-Host "  ❌ $msg" -ForegroundColor Red; $script:fail++ }
function Sect  { param($msg) Write-Host "`n━━━ $msg ━━━" -ForegroundColor Cyan }

if (-not $SubscriptionId) { $SubscriptionId = az account show --query id -o tsv 2>$null }

Sect "Resource Group"
$rgState = az group show --name $RgName --subscription $SubscriptionId `
  --query properties.provisioningState -o tsv 2>$null
if ($rgState -eq "Succeeded") { Pass "RG ${RgName}: Succeeded" } else { Fail "RG ${RgName}: $rgState" }

Sect "Data Services"
# Lookup actual names dynamically — resource names use resourceToken suffix, not simple env suffix
$cosmosName = az cosmosdb list --resource-group $RgName --subscription $SubscriptionId --query "[0].name" -o tsv 2>$null
$sbName = az servicebus namespace list --resource-group $RgName --subscription $SubscriptionId --query "[0].name" -o tsv 2>$null
$searchName = az search service list --resource-group $RgName --subscription $SubscriptionId --query "[0].name" -o tsv 2>$null

$resources = @(
  @{ label="Cosmos DB"; type="Microsoft.DocumentDB/databaseAccounts"; name=$cosmosName }
  @{ label="Service Bus"; type="Microsoft.ServiceBus/namespaces"; name=$sbName }
  @{ label="AI Search"; type="Microsoft.Search/searchServices"; name=$searchName }
)
foreach ($r in $resources) {
  $id = "/subscriptions/$SubscriptionId/resourceGroups/$RgName/providers/$($r.type)/$($r.name)"
  $state = az resource show --ids $id --query properties.provisioningState -o tsv 2>$null
  if ($state -eq "Succeeded") { Pass "$($r.label): $($r.name)" } else { Fail "$($r.label): $($r.name) ($state)" }
}

Sect "Functions"
$funcState = az functionapp show --name "func-intake-$EnvName" --resource-group $RgName `
  --subscription $SubscriptionId --query "properties.state" -o tsv 2>$null
if ($funcState) { Pass "Functions: func-intake-$EnvName ($funcState)" } else { Fail "Functions not found" }

Write-Host "`n━━━ Summary ━━━"
Write-Host "  Passed: $pass  Failed: $fail"
if ($fail -gt 0) { Write-Host "⚠️  Checks failed" -ForegroundColor Yellow; exit 1 }
else { Write-Host "✅ All passed" -ForegroundColor Green; exit 0 }
