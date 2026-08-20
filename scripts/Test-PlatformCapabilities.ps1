[CmdletBinding()]
param(
    [Parameter()]
    [string] $Location = "eastus2",

    [Parameter()]
    [string[]] $RequiredProviders = @(
        "Microsoft.App",
        "Microsoft.CognitiveServices",
        "Microsoft.ContainerRegistry",
        "Microsoft.DocumentDB",
        "Microsoft.Insights",
        "Microsoft.KeyVault",
        "Microsoft.MachineLearningServices",
        "Microsoft.OperationalInsights",
        "Microsoft.Search",
        "Microsoft.ServiceBus",
        "Microsoft.Storage",
        "Microsoft.Web"
    )
)

$ErrorActionPreference = "Stop"

function Invoke-AzJson {
    param([Parameter(Mandatory)][string[]] $Arguments)

    $output = & az @Arguments --output json
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI command failed: az $($Arguments -join ' ')"
    }

    return $output | ConvertFrom-Json
}

foreach ($command in @("az", "azd")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command '$command' is not installed or is not on PATH."
    }
}

$account = Invoke-AzJson -Arguments @("account", "show")
$locationMetadata = Invoke-AzJson -Arguments @("account", "list-locations")
$displayLocation = (
    $locationMetadata |
        Where-Object name -eq $Location |
        Select-Object -First 1
).displayName
if (-not $displayLocation) {
    throw "Azure location '$Location' is not available in the active subscription."
}

$azdVersion = & azd version
if ($LASTEXITCODE -ne 0) {
    throw "Azure Developer CLI is installed but could not run."
}

$providerResults = foreach ($provider in $RequiredProviders) {
    $state = & az provider show --namespace $provider --query registrationState --output tsv
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect provider '$provider'."
    }

    [pscustomobject]@{
        Namespace = $provider
        State = $state
        Ready = $state -eq "Registered"
    }
}

$resourceTypes = @(
    "Microsoft.CognitiveServices/accounts",
    "Microsoft.App/managedEnvironments",
    "Microsoft.App/containerApps",
    "Microsoft.DocumentDB/databaseAccounts",
    "Microsoft.Search/searchServices",
    "Microsoft.ServiceBus/namespaces",
    "Microsoft.Storage/storageAccounts",
    "Microsoft.KeyVault/vaults",
    "Microsoft.Web/sites",
    "Microsoft.OperationalInsights/workspaces",
    "Microsoft.Insights/components",
    "Microsoft.ContainerRegistry/registries"
)

$namespaceCache = @{}
$locationResults = foreach ($resourceType in $resourceTypes) {
    $namespace, $typeName = $resourceType.Split("/", 2)
    if (-not $namespaceCache.ContainsKey($namespace)) {
        $namespaceCache[$namespace] = Invoke-AzJson -Arguments @(
            "provider",
            "show",
            "--namespace",
            $namespace
        )
    }

    $metadata = $namespaceCache[$namespace].resourceTypes |
        Where-Object resourceType -eq $typeName |
        Select-Object -First 1

    [pscustomobject]@{
        ResourceType = $resourceType
        Location = $displayLocation
        Available = $null -ne $metadata -and $metadata.locations -contains $displayLocation
    }
}

$azdExtensions = & azd extension list --output json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect Azure Developer CLI extensions."
}

$requiredAzdExtensions = @(
    "azure.ai.agents",
    "azure.ai.connections",
    "azure.ai.projects",
    "azure.ai.toolboxes"
)

$extensionResults = foreach ($extension in $requiredAzdExtensions) {
    $installed = $azdExtensions | Where-Object id -eq $extension | Select-Object -First 1
    [pscustomobject]@{
        Id = $extension
        Installed = $null -ne $installed -and $installed.installedVersion
        Version = $installed.installedVersion
    }
}

$failures = @(
    $providerResults | Where-Object { -not $_.Ready }
    $locationResults | Where-Object { -not $_.Available }
    $extensionResults | Where-Object { -not $_.Installed }
)

$result = [ordered]@{
    checkedAt = (Get-Date).ToUniversalTime().ToString("O")
    subscription = [ordered]@{
        id = $account.id
        name = $account.name
        tenantId = $account.tenantId
        userType = $account.user.type
    }
    tooling = [ordered]@{
        azureCli = (Invoke-AzJson -Arguments @("version"))."azure-cli"
        azureDeveloperCli = $azdVersion
        extensions = $extensionResults
    }
    location = $Location
    providers = $providerResults
    resourceAvailability = $locationResults
    passed = $failures.Count -eq 0
}

$result | ConvertTo-Json -Depth 8

if (-not $result.passed) {
    throw "Azure platform capability preflight failed. Review the JSON output before provisioning."
}
