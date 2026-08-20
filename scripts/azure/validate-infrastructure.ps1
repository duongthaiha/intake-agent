[CmdletBinding()]
param(
  [switch]$SkipAzd
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$infraRoot = Join-Path $repoRoot 'infra'
$mainTemplate = Join-Path $infraRoot 'main.bicep'

function Invoke-Checked {
  param(
    [Parameter(Mandatory)]
    [string]$Description,
    [Parameter(Mandatory)]
    [scriptblock]$Command
  )

  Write-Host "==> $Description"
  & $Command
  if ($LASTEXITCODE -ne 0) {
    throw "$Description failed with exit code $LASTEXITCODE."
  }
}

Push-Location $repoRoot
try {
  Invoke-Checked 'Compile infra/main.bicep' {
    az bicep build --file $mainTemplate --stdout | Out-Null
  }

  Get-ChildItem -Path $infraRoot -Filter 'main.*.bicepparam' | ForEach-Object {
    $parameterFile = $_.FullName
    Invoke-Checked "Compile $($_.Name)" {
      az bicep build-params --file $parameterFile --stdout | Out-Null
    }
  }

  Get-ChildItem -Path $infraRoot -Recurse -Filter '*.json' | ForEach-Object {
    $null = Get-Content -Raw $_.FullName | ConvertFrom-Json -Depth 100
  }
  Write-Host '==> JSON documents parsed'

  if (-not $SkipAzd) {
    Invoke-Checked 'Parse azure.yaml with azd' {
      azd show --output json | Out-Null
    }
  }
}
finally {
  Pop-Location
}

Write-Host 'Infrastructure static validation passed.'
