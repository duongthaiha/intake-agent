param(
  [string]$EnvName = $env:AZURE_ENV_NAME,
  [string]$RedirectUri = $env:MCP_OAUTH_REDIRECT_URI
)
$ErrorActionPreference = "Stop"
if (-not $EnvName) { throw "AZURE_ENV_NAME is required" }
if (-not $RedirectUri) {
  throw "MCP_OAUTH_REDIRECT_URI is required; obtain the exact Foundry custom OAuth callback URI before running"
}

function Get-OrCreateApp([string]$Name, [string]$Callback = "") {
  $apps = @(az ad app list --filter "displayName eq '$Name'" -o json | ConvertFrom-Json)
  if ($apps.Count -gt 1) { throw "More than one app registration is named '$Name'; resolve ambiguity manually." }
  if ($apps.Count -eq 1) { return $apps[0] }
  if ($Callback) {
    return az ad app create --display-name $Name --sign-in-audience AzureADMyOrg `
      --web-redirect-uris $Callback -o json | ConvertFrom-Json
  }
  return az ad app create --display-name $Name --sign-in-audience AzureADMyOrg -o json | ConvertFrom-Json
}

$server = Get-OrCreateApp "intake-mcp-$EnvName"
$client = Get-OrCreateApp "intake-mcp-foundry-$EnvName" $RedirectUri
foreach ($appId in $server.appId,$client.appId) {
  az ad sp show --id $appId --only-show-errors 2>$null | Out-Null
  if ($LASTEXITCODE -ne 0) {
    az ad sp create --id $appId --only-show-errors | Out-Null
  }
}
$serverDetails = az rest --method get --uri "https://graph.microsoft.com/v1.0/applications/$($server.id)" -o json | ConvertFrom-Json
$scope = @($serverDetails.api.oauth2PermissionScopes | Where-Object value -eq "Intake.Tools.ReadWrite")[0]
$scopeId = if ($scope) { $scope.id } else { [guid]::NewGuid().ToString() }
$body = @{
  signInAudience = "AzureADMyOrg"
  identifierUris = @("api://$($server.appId)")
  api = @{
    requestedAccessTokenVersion = 2
    oauth2PermissionScopes = @(@{
      adminConsentDescription = "Access intake requester tools as the signed-in user"
      adminConsentDisplayName = "Access intake requester tools"
      id = $scopeId; isEnabled = $true; type = "User"
      userConsentDescription = "Access your intake requests"
      userConsentDisplayName = "Access your intake requests"
      value = "Intake.Tools.ReadWrite"
    })
    preAuthorizedApplications = @(@{ appId = $client.appId; delegatedPermissionIds = @($scopeId) })
  }
} | ConvertTo-Json -Depth 8 -Compress
az rest --method patch --uri "https://graph.microsoft.com/v1.0/applications/$($server.id)" `
  --headers "Content-Type=application/json" --body $body --only-show-errors | Out-Null
$clientBody = @{
  signInAudience = "AzureADMyOrg"
  web = @{ redirectUris = @($RedirectUri) }
} | ConvertTo-Json -Depth 4 -Compress
az rest --method patch --uri "https://graph.microsoft.com/v1.0/applications/$($client.id)" `
  --headers "Content-Type=application/json" --body $clientBody --only-show-errors | Out-Null

azd env set MCP_SERVER_APP_CLIENT_ID $server.appId
azd env set MCP_OAUTH_CLIENT_APP_ID $client.appId
azd env set MCP_OAUTH_CONNECTION_NAME "intake-mcp-oauth-$EnvName"
azd env set MCP_TOOLBOX_NAME "intake-mcp-v1-$EnvName"
azd env set MCP_TOOLBOX_SERVER_LABEL "intake_requester_tools"
$tenant = az account show --query tenantId -o tsv
Write-Host "Configured same-tenant Entra applications and delegated scope for tenant $tenant."
Write-Host "No client credential or tenant-wide admin consent was created."
