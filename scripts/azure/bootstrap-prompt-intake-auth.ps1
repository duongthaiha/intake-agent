# One-time, secretless Entra bootstrap for delegated prompt-agent MCP access.
param(
  [string]$EnvName = ($env:AZURE_ENV_NAME ?? "dev"),
  [string]$DisplayName = ""
)

$ErrorActionPreference = "Stop"
if (-not $DisplayName) { $DisplayName = "prompt-intake-mcp-$EnvName" }
$scopeValue = "access_as_user"

$appIds = @(
  az ad app list `
    --filter "displayName eq '$DisplayName'" `
    --query "[].appId" `
    --output tsv
) | Where-Object { $_ -and $_.Trim() }

if ($appIds.Count -gt 1) {
  throw "Multiple Entra applications named '$DisplayName' exist; refusing ambiguity."
}

if ($appIds.Count -eq 0) {
  $appId = (
    az ad app create `
      --display-name $DisplayName `
      --sign-in-audience AzureADMyOrg `
      --query appId `
      --output tsv
  ).Trim()
} else {
  $appId = $appIds[0].Trim()
}

$appObjectId = (az ad app show --id $appId --query id --output tsv).Trim()
az ad sp show --id $appId *> $null
if ($LASTEXITCODE -ne 0) {
  az ad sp create --id $appId --output none
}

$scopeId = (
  az rest `
    --method GET `
    --url "https://graph.microsoft.com/v1.0/applications/$appObjectId" `
    --query "api.oauth2PermissionScopes[?value=='$scopeValue'].id | [0]" `
    --output tsv
).Trim()
if (-not $scopeId) { $scopeId = [guid]::NewGuid().ToString() }

$body = @{
  identifierUris = @("api://$appId")
  api = @{
    requestedAccessTokenVersion = 2
    oauth2PermissionScopes = @(
      @{
        adminConsentDescription = "Allow the prompt intake agent to act for the signed-in user."
        adminConsentDisplayName = "Access the prompt intake MCP API"
        id = $scopeId
        isEnabled = $true
        type = "User"
        userConsentDescription = "Allow the prompt intake agent to access your intake requests."
        userConsentDisplayName = "Access your intake requests"
        value = $scopeValue
      }
    )
  }
} | ConvertTo-Json -Depth 6 -Compress

$tempFile = Join-Path $env:TEMP "prompt-intake-auth-$PID.json"
try {
  Set-Content -Path $tempFile -Value $body -Encoding utf8NoBOM
  az rest `
    --method PATCH `
    --url "https://graph.microsoft.com/v1.0/applications/$appObjectId" `
    --headers "Content-Type=application/json" `
    --body "@$tempFile" `
    --output none
} finally {
  Remove-Item -Path $tempFile -Force -ErrorAction SilentlyContinue
}

Write-Output "Prompt intake MCP Entra application is ready."
Write-Output "INTAKE_MCP_APP_CLIENT_ID=$appId"
Write-Output "INTAKE_MCP_AUDIENCE=api://$appId"
Write-Output "INTAKE_MCP_SCOPE=api://$appId/$scopeValue"
