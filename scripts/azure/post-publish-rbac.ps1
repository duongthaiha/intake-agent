[CmdletBinding()]
param(
  [string[]]$AgentPrincipalIds = @(
    $env:FOUNDRY_HOSTED_AGENT_PRINCIPAL_ID,
    $env:FOUNDRY_PROMPT_AGENT_PRINCIPAL_ID
  ),
  [string]$FoundryAccountId = $env:AZURE_FOUNDRY_ACCOUNT_ID,
  [string]$FoundryProjectId = $env:AZURE_FOUNDRY_PROJECT_ID,
  [string]$SearchResourceId = $(if ($env:AZURE_SEARCH_ENDPOINT -and $env:AZURE_RESOURCE_GROUP -and $env:AZURE_SUBSCRIPTION_ID) {
    $searchName = ([Uri]$env:AZURE_SEARCH_ENDPOINT).Host.Split('.')[0]
    "/subscriptions/$($env:AZURE_SUBSCRIPTION_ID)/resourceGroups/$($env:AZURE_RESOURCE_GROUP)/providers/Microsoft.Search/searchServices/$searchName"
  })
)

$ErrorActionPreference = 'Stop'
$principals = @($AgentPrincipalIds | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)
if ($principals.Count -eq 0) {
  throw 'At least one actual Foundry agent instance principal ID is required.'
}
foreach ($required in @{
  FoundryAccountId = $FoundryAccountId
  FoundryProjectId = $FoundryProjectId
  SearchResourceId = $SearchResourceId
}.GetEnumerator()) {
  if ([string]::IsNullOrWhiteSpace($required.Value)) {
    throw "$($required.Key) is required."
  }
}

function Ensure-Role {
  param(
    [string]$PrincipalId,
    [string]$Role,
    [string]$Scope
  )

  $count = az role assignment list `
    --assignee-object-id $PrincipalId `
    --scope $Scope `
    --query "[?roleDefinitionName=='$Role'] | length(@)" `
    --output tsv
  if ([int]$count -eq 0) {
    az role assignment create `
      --assignee-object-id $PrincipalId `
      --assignee-principal-type ServicePrincipal `
      --role $Role `
      --scope $Scope `
      --only-show-errors | Out-Null
  }
}

foreach ($principalId in $principals) {
  Ensure-Role -PrincipalId $principalId -Role 'Search Index Data Reader' -Scope $SearchResourceId
  Ensure-Role -PrincipalId $principalId -Role 'Cognitive Services User' -Scope $FoundryAccountId

  $consumerRole = az role definition list --name 'Foundry Agent Consumer' --query '[0].roleName' --output tsv 2>$null
  if ($consumerRole) {
    Ensure-Role -PrincipalId $principalId -Role $consumerRole -Scope $FoundryProjectId
  }
}

Write-Host 'Post-publish agent identity RBAC reconciled.'
