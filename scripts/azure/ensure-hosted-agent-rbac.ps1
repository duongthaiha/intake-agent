param(
  [string]$SubscriptionId = $env:AZURE_SUBSCRIPTION_ID,
  [string]$ResourceGroup = $env:AZURE_RESOURCE_GROUP,
  [string]$PrincipalId = $env:AGENT_RUNTIME_PRINCIPAL_ID,
  [string]$CosmosAccount = $env:AZURE_COSMOS_ACCOUNT_NAME,
  [string]$CosmosDatabase = $env:AZURE_COSMOS_DATABASE,
  [string]$StorageAccount = $env:AZURE_STORAGE_ACCOUNT_NAME,
  [string]$BlobContainer = $env:AZURE_STORAGE_ARTIFACTS_CONTAINER,
  [string]$ServiceBusNamespace = ($env:AZURE_SERVICEBUS_NAMESPACE -replace '\.servicebus\.windows\.net$', ''),
  [string]$ServiceBusQueue = $env:AZURE_SERVICEBUS_QUEUE,
  [string]$SearchService = $env:AZURE_SEARCH_SERVICE_NAME,
  [string]$FoundryAccount = $env:AZURE_AI_ACCOUNT_NAME,
  [switch]$PruneLegacyBroadAssignments
)

$ErrorActionPreference = "Stop"

foreach ($required in @{
  SubscriptionId = $SubscriptionId
  ResourceGroup = $ResourceGroup
  PrincipalId = $PrincipalId
  CosmosAccount = $CosmosAccount
  CosmosDatabase = $CosmosDatabase
  StorageAccount = $StorageAccount
  BlobContainer = $BlobContainer
  ServiceBusNamespace = $ServiceBusNamespace
  ServiceBusQueue = $ServiceBusQueue
  SearchService = $SearchService
  FoundryAccount = $FoundryAccount
}.GetEnumerator()) {
  if ([string]::IsNullOrWhiteSpace($required.Value)) {
    throw "$($required.Key) is required"
  }
}

az account set --subscription $SubscriptionId
$base = "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers"
$storageScope = "$base/Microsoft.Storage/storageAccounts/$StorageAccount"
$containerScope = "$storageScope/blobServices/default/containers/$BlobContainer"
$serviceBusScope = "$base/Microsoft.ServiceBus/namespaces/$ServiceBusNamespace"
$queueScope = "$serviceBusScope/queues/$ServiceBusQueue"
$searchScope = "$base/Microsoft.Search/searchServices/$SearchService"
$foundryScope = "$base/Microsoft.CognitiveServices/accounts/$FoundryAccount"
$cosmosScope = "$base/Microsoft.DocumentDB/databaseAccounts/$CosmosAccount"
$cosmosDatabaseScope = "$cosmosScope/dbs/$CosmosDatabase"
$cosmosContributorRole = "$cosmosScope/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"

function Ensure-AzureRole {
  param([string]$Role, [string]$Scope)

  $assignment = az role assignment list `
    --assignee-object-id $PrincipalId `
    --scope $Scope `
    --query "[?roleDefinitionName=='$Role' && scope=='$Scope'].id | [0]" `
    -o tsv
  if ($assignment) {
    Write-Host "present: $Role at $Scope"
    return
  }

  az role assignment create `
    --assignee-object-id $PrincipalId `
    --assignee-principal-type ServicePrincipal `
    --role $Role `
    --scope $Scope `
    --only-show-errors | Out-Null
  Write-Host "created: $Role at $Scope"
}

Ensure-AzureRole "Storage Blob Data Contributor" $containerScope
Ensure-AzureRole "Storage Blob Delegator" $storageScope
Ensure-AzureRole "Azure Service Bus Data Sender" $queueScope
Ensure-AzureRole "Search Index Data Reader" $searchScope
Ensure-AzureRole "Cognitive Services User" $foundryScope

$cosmosAssignment = az cosmosdb sql role assignment list `
  --resource-group $ResourceGroup `
  --account-name $CosmosAccount `
  --query "[?principalId=='$PrincipalId' && scope=='$cosmosDatabaseScope' && roleDefinitionId=='$cosmosContributorRole'].id | [0]" `
  -o tsv
if (-not $cosmosAssignment) {
  az cosmosdb sql role assignment create `
    --resource-group $ResourceGroup `
    --account-name $CosmosAccount `
    --principal-id $PrincipalId `
    --role-definition-id $cosmosContributorRole `
    --scope $cosmosDatabaseScope `
    --only-show-errors | Out-Null
  Write-Host "created: Cosmos DB Built-in Data Contributor at $cosmosDatabaseScope"
} else {
  Write-Host "present: Cosmos DB Built-in Data Contributor at $cosmosDatabaseScope"
}

if ($PruneLegacyBroadAssignments) {
  foreach ($legacy in @(
    @{ Role = "Storage Blob Data Contributor"; Scope = $storageScope },
    @{ Role = "Azure Service Bus Data Sender"; Scope = $serviceBusScope }
  )) {
    $ids = az role assignment list `
      --assignee-object-id $PrincipalId `
      --scope $legacy.Scope `
      --query "[?roleDefinitionName=='$($legacy.Role)' && scope=='$($legacy.Scope)'].id" `
      -o tsv
    foreach ($id in $ids) {
      az role assignment delete --ids $id --only-show-errors
      Write-Host "removed legacy broad assignment: $($legacy.Role) at $($legacy.Scope)"
    }
  }

  $legacyCosmosIds = az cosmosdb sql role assignment list `
    --resource-group $ResourceGroup `
    --account-name $CosmosAccount `
    --query "[?principalId=='$PrincipalId' && scope=='$cosmosScope' && roleDefinitionId=='$cosmosContributorRole'].id" `
    -o tsv
  foreach ($id in $legacyCosmosIds) {
    az cosmosdb sql role assignment delete `
      --resource-group $ResourceGroup `
      --account-name $CosmosAccount `
      --role-assignment-id ($id -split '/')[-1] `
      --yes `
      --only-show-errors
    Write-Host "removed legacy broad Cosmos assignment at $cosmosScope"
  }
}
