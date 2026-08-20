param(
    [Parameter(Mandatory = $true)]
    [string] $ProjectEndpoint,
    [Parameter(Mandatory = $true)]
    [string] $ProjectResourceId,
    [Parameter(Mandatory = $true)]
    [string] $AgentName
)

$ErrorActionPreference = "Stop"
$token = az account get-access-token `
    --resource https://ai.azure.com `
    --query accessToken `
    --output tsv
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($token)) {
    throw "Unable to acquire a Microsoft Foundry data-plane token."
}

$uri = "$($ProjectEndpoint.TrimEnd('/'))/agents/$AgentName`?api-version=v1"
$agent = Invoke-RestMethod `
    -Uri $uri `
    -Headers @{ Authorization = "Bearer $token" }
$principalId = $agent.instance_identity.principal_id
if ([string]::IsNullOrWhiteSpace($principalId)) {
    throw "Agent $AgentName does not expose an instance identity."
}

az role assignment create `
    --assignee-object-id $principalId `
    --assignee-principal-type ServicePrincipal `
    --role "Foundry User" `
    --scope $ProjectResourceId
if ($LASTEXITCODE -ne 0) {
    throw "Unable to grant Foundry User to agent identity $principalId."
}
