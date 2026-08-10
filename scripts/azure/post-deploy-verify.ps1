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

$databaseName = "intake"
$expectedContainers = @{
  "request-state" = "/requestId"
  "templates" = "/templateId"
  "idempotency" = "/scopeId"
}
foreach ($container in $expectedContainers.GetEnumerator()) {
  $partitionKey = az cosmosdb sql container show `
    --resource-group $RgName `
    --account-name $cosmosName `
    --database-name $databaseName `
    --name $container.Key `
    --query "resource.partitionKey.paths[0]" -o tsv 2>$null
  if ($partitionKey -eq $container.Value) {
    Pass "Cosmos container $($container.Key): $partitionKey"
  } else {
    Fail "Cosmos container $($container.Key): expected $($container.Value), got $partitionKey"
  }
}

$durableQueue = az servicebus queue show `
  --resource-group $RgName `
  --namespace-name $sbName `
  --name "domain-events-durable" `
  --query "{name:name,duplicate:requiresDuplicateDetection,status:status}" -o json 2>$null |
  ConvertFrom-Json
if ($durableQueue.name -eq "domain-events-durable" -and
    $durableQueue.duplicate -eq $true -and
    $durableQueue.status -eq "Active") {
  Pass "Service Bus durable outbox queue: active with duplicate detection"
} else {
  Fail "Service Bus durable outbox queue is missing or misconfigured"
}

Sect "Functions"
$funcName = "func-intake-$EnvName"
$funcId = "/subscriptions/$SubscriptionId/resourceGroups/$RgName/providers/Microsoft.Web/sites/$funcName"
$funcState = az resource show --ids $funcId --api-version 2023-12-01 `
  --query "properties.state" -o tsv 2>$null
if ($funcState -eq "Running") { Pass "Functions: $funcName ($funcState)" } else { Fail "Functions: $funcName ($funcState)" }

Write-Host "`n━━━ Summary ━━━"
Write-Host "  Passed: $pass  Failed: $fail"
if ($fail -gt 0) { Write-Host "⚠️  Checks failed" -ForegroundColor Yellow; exit 1 }
else { Write-Host "✅ All passed" -ForegroundColor Green; exit 0 }
