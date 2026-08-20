[CmdletBinding()]
param(
  [string]$ResourceGroup = $env:AZURE_RESOURCE_GROUP,
  [string]$EnvironmentName = $env:AZURE_CONTAINER_APPS_ENVIRONMENT_NAME,
  [string]$VirtualNetworkId = $env:AZURE_VIRTUAL_NETWORK_ID
)

$ErrorActionPreference = 'Stop'

function Invoke-Az {
  param(
    [Parameter(Mandatory)]
    [scriptblock]$Command,
    [Parameter(Mandatory)]
    [string]$Description
  )

  $result = & $Command
  if ($LASTEXITCODE -ne 0) {
    throw "$Description failed with exit code $LASTEXITCODE."
  }
  return $result
}

foreach ($required in @{
  ResourceGroup = $ResourceGroup
  EnvironmentName = $EnvironmentName
  VirtualNetworkId = $VirtualNetworkId
}.GetEnumerator()) {
  if ([string]::IsNullOrWhiteSpace($required.Value)) {
    throw "$($required.Key) is required."
  }
}

$environmentJson = Invoke-Az -Description 'Read the Container Apps environment' -Command {
  az containerapp env show `
    --resource-group $ResourceGroup `
    --name $EnvironmentName `
    --query '{domain:properties.defaultDomain,ip:properties.staticIp}' `
    --output json
}
$environment = $environmentJson | ConvertFrom-Json

if (-not $environment.domain -or -not $environment.ip) {
  throw 'Container Apps environment did not return an internal default domain and static IP.'
}

$zone = az network private-dns zone show `
  --resource-group $ResourceGroup `
  --name $environment.domain `
  --query name `
  --output tsv `
  --only-show-errors 2>$null
if ($LASTEXITCODE -ne 0 -or -not $zone) {
  Invoke-Az -Description 'Create the Container Apps private DNS zone' -Command {
    az network private-dns zone create `
      --resource-group $ResourceGroup `
      --name $environment.domain `
      --only-show-errors
  } | Out-Null
}

$link = az network private-dns link vnet show `
  --resource-group $ResourceGroup `
  --zone-name $environment.domain `
  --name 'intake-vnet' `
  --query name `
  --output tsv `
  --only-show-errors 2>$null
if ($LASTEXITCODE -ne 0 -or -not $link) {
  Invoke-Az -Description 'Link the Container Apps private DNS zone' -Command {
    az network private-dns link vnet create `
      --resource-group $ResourceGroup `
      --zone-name $environment.domain `
      --name 'intake-vnet' `
      --virtual-network $VirtualNetworkId `
      --registration-enabled false `
      --only-show-errors
  } | Out-Null
}

foreach ($recordName in @('@', '*')) {
  $addresses = az network private-dns record-set a show `
    --resource-group $ResourceGroup `
    --zone-name $environment.domain `
    --name $recordName `
    --query 'aRecords[].ipv4Address' `
    --output tsv `
    --only-show-errors 2>$null
  if ($LASTEXITCODE -ne 0) {
    Invoke-Az -Description "Create DNS record set '$recordName'" -Command {
      az network private-dns record-set a create `
      --resource-group $ResourceGroup `
      --zone-name $environment.domain `
      --name $recordName `
      --ttl 300 `
      --only-show-errors
    } | Out-Null
    $addresses = @()
  }
  if ($addresses -notcontains $environment.ip) {
    Invoke-Az -Description "Add DNS record '$recordName'" -Command {
      az network private-dns record-set a add-record `
      --resource-group $ResourceGroup `
      --zone-name $environment.domain `
      --record-set-name $recordName `
      --ipv4-address $environment.ip `
      --only-show-errors
    } | Out-Null
  }
}

Write-Host "Configured private DNS for $($environment.domain) -> $($environment.ip)."
