$ErrorActionPreference = "Stop"
$required = "AZURE_SUBSCRIPTION_ID","AZURE_RESOURCE_GROUP","AZURE_MCP_CONTAINER_APP_NAME",
  "MCP_RUNTIME_PRINCIPAL_ID","AGENT_RUNTIME_PRINCIPAL_ID","AZURE_STORAGE_ACCOUNT_NAME",
  "AZURE_SERVICEBUS_NAMESPACE","AZURE_COSMOS_ACCOUNT_NAME"
foreach ($name in $required) {
  if (-not [Environment]::GetEnvironmentVariable($name)) { throw "$name is required" }
}

az account set --subscription $env:AZURE_SUBSCRIPTION_ID
$app = az containerapp show -g $env:AZURE_RESOURCE_GROUP `
  -n $env:AZURE_MCP_CONTAINER_APP_NAME -o json | ConvertFrom-Json
if ($app.properties.provisioningState -ne "Succeeded") { throw "MCP Container App provisioning did not succeed" }
if (-not $app.properties.latestRevisionName -or
    $app.properties.latestRevisionName -ne $app.properties.latestReadyRevisionName) {
  throw "MCP latest revision is not ready; Hosted Agent data access was not removed"
}
if ($app.properties.configuration.ingress.external) { throw "MCP ingress is public; refusing cutover" }

$base = "/subscriptions/$($env:AZURE_SUBSCRIPTION_ID)/resourceGroups/$($env:AZURE_RESOURCE_GROUP)/providers"
$storage = "$base/Microsoft.Storage/storageAccounts/$($env:AZURE_STORAGE_ACCOUNT_NAME)"
$sbName = $env:AZURE_SERVICEBUS_NAMESPACE -replace '\.servicebus\.windows\.net$',''
$serviceBus = "$base/Microsoft.ServiceBus/namespaces/$sbName"
foreach ($spec in @(
  @("Storage Blob Data Contributor",$storage),
  @("Azure Service Bus Data Sender",$serviceBus)
)) {
  $count = az role assignment list --assignee-object-id $env:MCP_RUNTIME_PRINCIPAL_ID `
    --all --query "[?roleDefinitionName=='$($spec[0])' && scope=='$($spec[1])'] | length(@)" -o tsv
  if ([int]$count -lt 1) { throw "MCP identity is missing $($spec[0]); refusing cutover" }
}
$mcpCosmos = az cosmosdb sql role assignment list -g $env:AZURE_RESOURCE_GROUP `
  -a $env:AZURE_COSMOS_ACCOUNT_NAME `
  --query "[?principalId=='$($env:MCP_RUNTIME_PRINCIPAL_ID)'] | length(@)" -o tsv
if ([int]$mcpCosmos -lt 1) { throw "MCP identity is missing Cosmos data access; refusing cutover" }

if ($env:MCP_DATA_PLANE_CUTOVER_APPROVED -ne "true") {
  Write-Host "MCP revision is ready. Hosted Agent data-plane roles were retained."
  Write-Host "Complete delegated-user Toolbox verification, record approval, then rerun with MCP_DATA_PLANE_CUTOVER_APPROVED=true."
  exit 0
}

foreach ($spec in @(
  @("Storage Blob Data Contributor",$storage),
  @("Storage Blob Delegator",$storage),
  @("Azure Service Bus Data Sender",$serviceBus)
)) {
  $ids = az role assignment list --assignee-object-id $env:AGENT_RUNTIME_PRINCIPAL_ID `
    --all --query "[?roleDefinitionName=='$($spec[0])' && starts_with(scope, '$($spec[1])')].id" -o tsv
  foreach ($id in $ids) {
    az role assignment delete --ids $id --only-show-errors
    Write-Host "removed Hosted Agent runtime role: $($spec[0])"
  }
}
$ids = az cosmosdb sql role assignment list -g $env:AZURE_RESOURCE_GROUP `
  -a $env:AZURE_COSMOS_ACCOUNT_NAME `
  --query "[?principalId=='$($env:AGENT_RUNTIME_PRINCIPAL_ID)'].id" -o tsv
foreach ($id in $ids) {
  az cosmosdb sql role assignment delete -g $env:AZURE_RESOURCE_GROUP `
    -a $env:AZURE_COSMOS_ACCOUNT_NAME --role-assignment-id ($id -split '/')[-1] `
    --yes --only-show-errors
  Write-Host "removed Hosted Agent Cosmos data-plane assignment"
}
Write-Host "MCP revision ready and Hosted Agent runtime data-plane cutover complete."
