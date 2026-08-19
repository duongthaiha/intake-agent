param(
  [string]$SubscriptionId = $env:AZURE_SUBSCRIPTION_ID,
  [string]$ResourceGroup = $env:AZURE_RESOURCE_GROUP,
  [string]$PrincipalId = $env:AGENT_RUNTIME_PRINCIPAL_ID,
  [string]$SearchService = $env:AZURE_SEARCH_SERVICE_NAME,
  [string]$FoundryAccount = $env:AZURE_AI_ACCOUNT_NAME
)
$ErrorActionPreference = "Stop"
foreach ($required in @{
  SubscriptionId = $SubscriptionId; ResourceGroup = $ResourceGroup
  PrincipalId = $PrincipalId; SearchService = $SearchService
  FoundryAccount = $FoundryAccount
}.GetEnumerator()) {
  if ([string]::IsNullOrWhiteSpace($required.Value)) { throw "$($required.Key) is required" }
}

az account set --subscription $SubscriptionId
$base = "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers"
function Ensure-AzureRole([string]$Role, [string]$Scope) {
  $count = az role assignment list --assignee-object-id $PrincipalId --scope $Scope `
    --query "[?roleDefinitionName=='$Role' && scope=='$Scope'] | length(@)" -o tsv
  if ([int]$count -gt 0) { Write-Host "present: $Role"; return }
  az role assignment create --assignee-object-id $PrincipalId `
    --assignee-principal-type ServicePrincipal --role $Role --scope $Scope `
    --only-show-errors | Out-Null
  Write-Host "created: $Role"
}

Ensure-AzureRole "Search Index Data Reader" "$base/Microsoft.Search/searchServices/$SearchService"
Ensure-AzureRole "Cognitive Services User" "$base/Microsoft.CognitiveServices/accounts/$FoundryAccount"
