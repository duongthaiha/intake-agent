# scripts/azure/post-deploy-verify.ps1 — Windows/pwsh counterpart of
# post-deploy-verify.sh. Kept materially aligned with the Bash version: the
# same sections, the same resources, and the same blocking exit semantics.
#
# Foundry outputs are read from the OS environment when the caller exported
# them, and otherwise resolved from the azd environment (`azd provision`
# persists every Bicep output there, but azd only injects them into hook
# processes — not into an ordinary workflow step).
param(
  [string]$EnvName = ($env:AZURE_ENV_NAME ?? "dev"),
  [string]$SubscriptionId = ($env:AZURE_SUBSCRIPTION_ID ?? (az account show --query id -o tsv)),
  [string]$ResourceGroup = ($env:AZURE_RESOURCE_GROUP ?? "rg-intake-$($env:AZURE_ENV_NAME ?? 'dev')"),
  [string]$ProjectEndpoint = $env:AZURE_AI_PROJECT_ENDPOINT,
  [string]$FoundryAccountName = $env:AZURE_AI_ACCOUNT_NAME
)
$ErrorActionPreference = "Continue"; $pass = 0; $fail = 0
function Pass($m) { Write-Host "  ✅ $m"; $script:pass++ }
function Fail($m) { Write-Host "  ❌ $m"; $script:fail++ }
function Check($m, [scriptblock]$action) { try { & $action | Out-Null; if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "exit $LASTEXITCODE" }; Pass $m } catch { Fail $m } }
function Sect($m) { Write-Host "`n━━━ $m ━━━" }
function Get-AzdEnvValue($key) {
  try {
    $value = (azd env get-value $key --environment $EnvName --no-prompt 2>$null |
      Where-Object { $_ -and $_.Trim() } | Select-Object -Last 1)
    if ($value) { return $value.Trim() }
  } catch { }
  return ""
}

Sect "Resolving deployment outputs"
if (-not $ProjectEndpoint) { $ProjectEndpoint = Get-AzdEnvValue "AZURE_AI_PROJECT_ENDPOINT" }
if ($ProjectEndpoint -match '^https?://') {
  Pass "Foundry project endpoint resolved"
} else {
  Fail "AZURE_AI_PROJECT_ENDPOINT unavailable from the environment or 'azd env get-value'"
  $ProjectEndpoint = ""
}

# Verify the Foundry account this deployment actually produced, rather than
# whichever Cognitive Services account happens to be listed first in the RG.
if (-not $FoundryAccountName) { $FoundryAccountName = Get-AzdEnvValue "AZURE_AI_ACCOUNT_NAME" }
if ($FoundryAccountName -match '^[A-Za-z0-9][A-Za-z0-9-]*$') {
  Pass "Foundry account name resolved from azd outputs: $FoundryAccountName"
} else {
  Fail "AZURE_AI_ACCOUNT_NAME unavailable from the environment or 'azd env get-value'"
  $FoundryAccountName = ""
}

Sect "Foundation and data resources"
Check "Resource group provisioned" { if ((az group show -n $ResourceGroup --subscription $SubscriptionId --query properties.provisioningState -o tsv) -ne "Succeeded") { throw } }
$cosmos = az cosmosdb list -g $ResourceGroup --subscription $SubscriptionId --query "[0].name" -o tsv
$serviceBus = az servicebus namespace list -g $ResourceGroup --subscription $SubscriptionId --query "[0].name" -o tsv
$search = az search service list -g $ResourceGroup --subscription $SubscriptionId --query "[0].name" -o tsv
$storage = az storage account list -g $ResourceGroup --subscription $SubscriptionId --query "[0].name" -o tsv
foreach ($pair in @(@("Cosmos DB",$cosmos),@("Service Bus",$serviceBus),@("AI Search",$search),@("Storage",$storage))) {
  if ($pair[1]) { Pass "$($pair[0]) present" } else { Fail "Required data resource missing: $($pair[0])" }
}
if ($cosmos) { Check "Cosmos DB provisioned" { if ((az cosmosdb show -g $ResourceGroup -n $cosmos --query provisioningState -o tsv) -ne "Succeeded") { throw } } }
if ($serviceBus) { Check "Service Bus provisioned" { if ((az servicebus namespace show -g $ResourceGroup -n $serviceBus --query provisioningState -o tsv) -ne "Succeeded") { throw } } }
if ($search) { Check "AI Search provisioned" { if ((az search service show -g $ResourceGroup -n $search --query provisioningState -o tsv) -ne "Succeeded") { throw } } }
if ($storage) { Check "Storage provisioned" { if ((az storage account show -g $ResourceGroup -n $storage --query provisioningState -o tsv) -ne "Succeeded") { throw } } }

foreach ($spec in @(@("request-state","/requestId"),@("templates","/templateId"),@("idempotency","/scopeId"))) {
  $actual = az cosmosdb sql container show -g $ResourceGroup -a $cosmos -d intake -n $spec[0] --query resource.partitionKey.paths[0] -o tsv
  if ($actual -eq $spec[1]) { Pass "Cosmos container $($spec[0])" } else { Fail "Cosmos container $($spec[0]) partition key" }
}

# Status and duplicate detection are asserted as two independent scalar
# queries, mirroring the Bash version.
if ($serviceBus) {
  $queueStatus = az servicebus queue show -g $ResourceGroup --namespace-name $serviceBus -n domain-events-durable --query status -o tsv
  $queueDedupe = az servicebus queue show -g $ResourceGroup --namespace-name $serviceBus -n domain-events-durable --query requiresDuplicateDetection -o tsv
  if ($queueStatus -eq "Active") { Pass "Service Bus durable queue is Active" } else { Fail "Service Bus durable queue status: $(if ($queueStatus) { $queueStatus } else { 'unavailable' })" }
  if ("$queueDedupe".ToLowerInvariant() -eq "true") { Pass "Service Bus durable queue has duplicate detection enabled" } else { Fail "Service Bus durable queue duplicate detection: $(if ($queueDedupe) { $queueDedupe } else { 'unavailable' })" }
} else {
  Fail "Service Bus durable queue could not be checked: no namespace found"
}

Sect "Application and identities"
Check "Function App is Running" { if ((az functionapp show -g $ResourceGroup -n "func-intake-$EnvName" --query state -o tsv) -ne "Running") { throw } }
foreach ($identity in "agent","worker","eval","notify","runner","mcp") { Check "Managed identity id-intake-$identity-$EnvName" { az identity show -g $ResourceGroup -n "id-intake-$identity-$EnvName" } }

Sect "Runner bootstrap resources"
$acr = az acr list -g $ResourceGroup --subscription $SubscriptionId --query "[?tags.'azd-env-name'=='$EnvName'].name | [0]" -o tsv
if ($acr) {
  Pass "Runner ACR present: $acr"
  Check "Runner ACR public access disabled" { if ((az acr show -g $ResourceGroup -n $acr --query publicNetworkAccess -o tsv) -ne "Disabled") { throw } }
} else { Fail "Runner ACR missing" }
$job = "job-intake-runner-$EnvName"
Check "Runner job present" { az containerapp job show -g $ResourceGroup -n $job }
Check "Runner job event-triggered" { if ((az containerapp job show -g $ResourceGroup -n $job --query properties.configuration.triggerType -o tsv) -ne "Event") { throw } }

Sect "Hosted Agent and private path"
# Flags below are confirmed against microsoft.foundry (azd ai agent):
#   show   — [name], global -e/--environment, --no-prompt, -o/--output json|table
#   invoke — [name] [message], --new-session, -t/--timeout <seconds>, plus the
#            same global flags. The real remote invocation is intentionally
#            retained: it is the only check that proves the private data path.
Check "Hosted Agent show succeeded" { azd ai agent show intake-agent --environment $EnvName --no-prompt --output json }
Check "Hosted Agent private invocation succeeded" { azd ai agent invoke intake-agent "Return exactly: health check passed." --environment $EnvName --new-session --timeout 120 --no-prompt }
if ($ProjectEndpoint) {
  $hostName = ([uri]$ProjectEndpoint).Host
  try { $ip = [Net.Dns]::GetHostAddresses($hostName)[0].ToString() } catch { $ip = "" }
  if ($ip -match '^10\.|^192\.168\.|^172\.(1[6-9]|2[0-9]|3[0-1])\.') { Pass "Foundry private DNS: $hostName -> $ip" } else { Fail "Foundry private DNS is not RFC1918: $(if ($ip) { $ip } else { 'no answer' })" }
  try { $response = Invoke-WebRequest -Uri "https://$hostName/" -TimeoutSec 15 -UseBasicParsing; $code = $response.StatusCode } catch { $code = $_.Exception.Response.StatusCode.value__ }
  if ($code) { Pass "Foundry private TLS responds (HTTP $code)" } else { Fail "Foundry private TLS did not respond" }
}
if ($FoundryAccountName) {
  Check "Foundry public access disabled" { if ((az cognitiveservices account show -g $ResourceGroup -n $FoundryAccountName --query properties.publicNetworkAccess -o tsv) -ne "Disabled") { throw } }
}

Sect "Prompt Agent and private MCP path"
$mcpApp = Get-AzdEnvValue "INTAKE_MCP_APP_NAME"
$mcpUrl = Get-AzdEnvValue "INTAKE_MCP_SERVER_URL"
$mcpConnection = Get-AzdEnvValue "INTAKE_MCP_CONNECTION_NAME"
$mcpModel = Get-AzdEnvValue "AZURE_AI_MODEL_DEPLOYMENT_NAME"

if ($mcpApp) {
  Check "Prompt intake MCP Container App exists" { az containerapp show -g $ResourceGroup -n $mcpApp }
  $mcpEnvironmentId = az containerapp show -g $ResourceGroup -n $mcpApp --query properties.environmentId -o tsv
  $mcpEnvironmentName = if ($mcpEnvironmentId) { Split-Path $mcpEnvironmentId -Leaf } else { "" }
  if ($mcpEnvironmentName) {
    Check "Prompt intake MCP environment is internal" {
      if ((az containerapp env show -g $ResourceGroup -n $mcpEnvironmentName --query properties.vnetConfiguration.internal -o tsv) -ne "true") { throw }
    }
  } else {
    Fail "Prompt intake MCP environment could not be resolved"
  }
} else {
  Fail "INTAKE_MCP_APP_NAME unavailable from azd outputs"
}

if ($mcpUrl -match '^https://') {
  $mcpUri = [uri]$mcpUrl
  try { $mcpIp = [Net.Dns]::GetHostAddresses($mcpUri.Host)[0].ToString() } catch { $mcpIp = "" }
  if ($mcpIp -match '^10\.|^192\.168\.|^172\.(1[6-9]|2[0-9]|3[0-1])\.') {
    Pass "Prompt intake MCP private DNS: $($mcpUri.Host) -> $mcpIp"
  } else {
    Fail "Prompt intake MCP DNS is not RFC1918: $(if ($mcpIp) { $mcpIp } else { 'no answer' })"
  }
  $mcpBase = $mcpUrl -replace '/mcp$', ''
  Check "Prompt intake MCP health responds" { Invoke-WebRequest -Uri "$mcpBase/health" -TimeoutSec 15 -UseBasicParsing }
  try {
    $response = Invoke-WebRequest -Uri $mcpUrl -TimeoutSec 15 -UseBasicParsing
    $mcpUnauthorizedStatus = $response.StatusCode
  } catch {
    $mcpUnauthorizedStatus = $_.Exception.Response.StatusCode.value__
  }
  if ($mcpUnauthorizedStatus -eq 401) {
    Pass "Prompt intake MCP rejects unauthenticated calls"
  } else {
    Fail "Prompt intake MCP unauthenticated status: $(if ($mcpUnauthorizedStatus) { $mcpUnauthorizedStatus } else { 'unavailable' })"
  }
} else {
  Fail "INTAKE_MCP_SERVER_URL unavailable from azd outputs"
}

if ($mcpConnection -and $ProjectEndpoint) {
  Check "Delegated MCP project connection exists" {
    azd ai connection show $mcpConnection --project-endpoint $ProjectEndpoint --no-prompt --output json
  }
} else {
  Fail "Prompt intake MCP connection inputs unavailable"
}

Check "Prompt Agent definition verified" {
  python scripts/foundry/verify_prompt_agent.py `
    --project-endpoint $ProjectEndpoint `
    --model $mcpModel `
    --server-url $mcpUrl `
    --connection-name $mcpConnection
}

Write-Host "`n━━━ Post-Deploy Verification Summary ━━━"; Write-Host "  Passed: $pass"; Write-Host "  Failed: $fail"
if ($fail -gt 0) { exit 1 }
