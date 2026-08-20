param(
    [Parameter(Mandatory = $true)]
    [string] $ProjectEndpoint,
    [Parameter(Mandatory = $true)]
    [string] $AgentName,
    [Parameter(Mandatory = $true)]
    [string] $BotServiceArmId,
    [ValidateSet("Shared", "Tenant", "Personal")]
    [string] $PublishScope = "Shared",
    [string] $MetadataPath = ""
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if ([string]::IsNullOrWhiteSpace($MetadataPath)) {
    $MetadataPath = Join-Path $root "foundry\teams\publish-metadata.json"
}

$payload = Get-Content -Raw $MetadataPath | ConvertFrom-Json
$payload | Add-Member -NotePropertyName botServiceArmId -NotePropertyValue $BotServiceArmId -Force
$payload.publishScope = $PublishScope
$body = $payload | ConvertTo-Json -Depth 10
$token = az account get-access-token `
    --resource https://ai.azure.com `
    --query accessToken `
    --output tsv
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($token)) {
    throw "Unable to acquire a Microsoft Foundry data-plane token."
}

$uri = "$($ProjectEndpoint.TrimEnd('/'))/agents/$AgentName/microsoft365/publish?api-version=v1"
Invoke-RestMethod `
    -Uri $uri `
    -Method Post `
    -Headers @{ Authorization = "Bearer $token" } `
    -ContentType "application/json" `
    -Body $body
