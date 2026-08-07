// intake-agent — Main Bicep orchestrator
// Scope: subscription — creates resource group and delegates to modules.
// Deploy via: azd provision
targetScope = 'subscription'

// ---------------------------------------------------------------------------
// Parameters
// ---------------------------------------------------------------------------

@minLength(1)
@maxLength(64)
@description('Environment name (azd env name). Used in all resource names.')
param environmentName string

@minLength(1)
@description('Azure region for all resources.')
param location string

@description('Object ID of the identity running the deployment (for KV access policy during bootstrap).')
param principalId string = ''

@description('Deploy Azure AI Foundry hub, project and AI Services account. Requires Microsoft.MachineLearningServices provider to be registered.')
param deployFoundry bool = false

@description('Deploy Azure Bot Service resource. Requires Microsoft.BotService provider registered + Teams publishing spike resolved.')
param deployBotService bool = false

@description('Deploy private endpoints and configure public network access. Set true only after connectivity spike confirms Foundry → private data-plane path.')
param deployPrivateEndpoints bool = false

@description('Override region for AI Search service only. eastus2 has been observed to have InsufficientResourcesAvailable for new AI Search services; set to eastus as fallback.')
param searchServiceLocation string = 'eastus'

@description('Tags applied to every resource in the resource group.')
param tags object = {
  'azd-env-name': environmentName
  project: 'intake-agent'
  environment: environmentName
  'managed-by': 'azd-bicep'
}

// ---------------------------------------------------------------------------
// Variables — deterministic unique token
// ---------------------------------------------------------------------------

// Stable 13-char token scoped to subscription + environment + location.
// Used as suffix for globally-unique resource names (storage, KV).
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))

var resourceGroupName = 'rg-intake-${environmentName}'

// Subnet ID constructed without referencing network module outputs to avoid circular dependency
// (network module references storage for private endpoint DNS — storage needs functionsSubnetId for VNet rule)
var vnetName = 'vnet-intake-${environmentName}'
var functionsSubnetId = '/subscriptions/${subscription().subscriptionId}/resourceGroups/${resourceGroupName}/providers/Microsoft.Network/virtualNetworks/${vnetName}/subnets/snet-functions'
// Pre-computed resource names — used in both the resource modules and cross-module references
// to avoid circular dependencies when private endpoint modules need these names.
var storageAccountName = 'st${take(resourceToken, 10)}'
var cosmosAccountName = 'cosmos-${take(resourceToken, 10)}'
var serviceBusName = 'sb-${take(resourceToken, 12)}'
var keyVaultName = 'kv-${take(resourceToken, 10)}jeg'
var searchServiceName = 'srch-${take(resourceToken, 12)}'

// ---------------------------------------------------------------------------
// Resource group
// ---------------------------------------------------------------------------

resource rg 'Microsoft.Resources/resourceGroups@2024-07-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

// ---------------------------------------------------------------------------
// Monitoring — Log Analytics + Application Insights
// ---------------------------------------------------------------------------

module monitoring 'modules/monitoring.bicep' = {
  scope: rg
  name: 'monitoring'
  params: {
    location: location
    tags: tags
    logAnalyticsName: 'log-intake-${environmentName}'
    appInsightsName: 'appi-intake-${environmentName}'
  }
}

// ---------------------------------------------------------------------------
// Network — VNet, subnets, private DNS zones, optional private endpoints
// ---------------------------------------------------------------------------

module network 'modules/network.bicep' = {
  scope: rg
  name: 'network'
  params: {
    location: location
    tags: tags
    vnetName: 'vnet-intake-${environmentName}'
    deployPrivateEndpoints: deployPrivateEndpoints
    cosmosAccountName: cosmosAccountName
    storageAccountName: storageAccountName
    serviceBusNamespaceName: serviceBusName
    searchServiceName: searchServiceName
    keyVaultName: keyVaultName
  }
}

// ---------------------------------------------------------------------------
// Managed identities
// ---------------------------------------------------------------------------

module identity 'modules/identity.bicep' = {
  scope: rg
  name: 'identity'
  params: {
    location: location
    tags: tags
    environmentName: environmentName
  }
}

// ---------------------------------------------------------------------------
// Key Vault
// ---------------------------------------------------------------------------

module keyvault 'modules/keyvault.bicep' = {
  scope: rg
  name: 'keyvault'
  params: {
    location: location
    tags: tags
    keyVaultName: 'kv-${take(resourceToken, 16)}'
    deployPrivateEndpoints: deployPrivateEndpoints
    workerIdentityPrincipalId: identity.outputs.workerIdentityPrincipalId
    deployerPrincipalId: principalId
  }
}

// ---------------------------------------------------------------------------
// Storage account
// ---------------------------------------------------------------------------

module storage 'modules/storage.bicep' = {
  scope: rg
  name: 'storage'
  params: {
    location: location
    tags: tags
    storageAccountName: 'st${take(resourceToken, 10)}'
    deployPrivateEndpoints: deployPrivateEndpoints
    workerIdentityPrincipalId: identity.outputs.workerIdentityPrincipalId
    evalIdentityPrincipalId: identity.outputs.evalIdentityPrincipalId
    functionsMIPrincipalId: identity.outputs.workerIdentityPrincipalId
    deployerPrincipalId: principalId
    functionsSubnetId: functionsSubnetId
  }
  dependsOn: [network]
}

// ---------------------------------------------------------------------------
// Cosmos DB
// ---------------------------------------------------------------------------

module cosmos 'modules/cosmos.bicep' = {
  scope: rg
  name: 'cosmos'
  params: {
    location: location
    tags: tags
    accountName: 'cosmos-${take(resourceToken, 10)}'
    deployPrivateEndpoints: deployPrivateEndpoints
    agentIdentityPrincipalId: identity.outputs.agentIdentityPrincipalId
    workerIdentityPrincipalId: identity.outputs.workerIdentityPrincipalId
  }
}

// ---------------------------------------------------------------------------
// Service Bus
// ---------------------------------------------------------------------------

module servicebus 'modules/servicebus.bicep' = {
  scope: rg
  name: 'servicebus'
  params: {
    location: location
    tags: tags
    namespaceName: 'sb-${take(resourceToken, 12)}'
    deployPrivateEndpoints: deployPrivateEndpoints
    agentIdentityPrincipalId: identity.outputs.agentIdentityPrincipalId
    workerIdentityPrincipalId: identity.outputs.workerIdentityPrincipalId
  }
}

// ---------------------------------------------------------------------------
// AI Search
// ---------------------------------------------------------------------------

module search 'modules/search.bicep' = {
  scope: rg
  name: 'search'
  params: {
    location: searchServiceLocation
    tags: tags
    searchServiceName: 'srch-${take(resourceToken, 12)}'
    deployPrivateEndpoints: deployPrivateEndpoints
    agentIdentityPrincipalId: identity.outputs.agentIdentityPrincipalId
  }
}

// ---------------------------------------------------------------------------
// Azure Functions (Flex Consumption)
// ---------------------------------------------------------------------------

module functions 'modules/functions.bicep' = {
  scope: rg
  name: 'functions'
  params: {
    location: location
    tags: tags
    functionAppName: 'func-intake-${environmentName}'
    planName: 'asp-intake-${environmentName}'
    storageAccountName: storage.outputs.accountName
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    workerIdentityId: identity.outputs.workerIdentityId
    workerIdentityClientId: identity.outputs.workerIdentityClientId
    cosmosEndpoint: cosmos.outputs.endpoint
    cosmosDatabase: cosmos.outputs.databaseName
    serviceBusNamespace: servicebus.outputs.namespaceFqdn
    serviceBusQueue: servicebus.outputs.queueName
    blobEndpoint: storage.outputs.blobEndpoint
    artifactsContainer: storage.outputs.artifactsContainer
    keyVaultUri: keyvault.outputs.vaultUri
    environmentName: environmentName
    vnetIntegrationSubnetId: network.outputs.functionsSubnetId
  }
}

// ---------------------------------------------------------------------------
// Container Apps environment + evaluation job
// ---------------------------------------------------------------------------

module containerApps 'modules/container-apps.bicep' = {
  scope: rg
  name: 'containerApps'
  params: {
    location: location
    tags: tags
    environmentName: 'cae-intake-${environmentName}'
    evalJobName: 'job-intake-eval-${environmentName}'
    logAnalyticsWorkspaceCustomerId: monitoring.outputs.logAnalyticsCustomerId
    logAnalyticsSharedKey: monitoring.outputs.logAnalyticsSharedKey
    evalIdentityId: identity.outputs.evalIdentityId
    evalIdentityClientId: identity.outputs.evalIdentityClientId
    storageEndpoint: storage.outputs.blobEndpoint
    evalContainer: storage.outputs.evalContainer
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    subnetId: network.outputs.containerAppsSubnetId
    environmentNameTag: environmentName
  }
}

// ---------------------------------------------------------------------------
// Azure AI Foundry (hub + project + AI Services) — gated
// ---------------------------------------------------------------------------

module foundry 'modules/foundry.bicep' = if (deployFoundry) {
  scope: rg
  name: 'foundry'
  params: {
    location: location
    tags: tags
    hubName: 'aihub-intake-${environmentName}'
    projectName: 'aiproj-intake-${environmentName}'
    aiServicesName: 'ais-intake-${environmentName}'
    storageAccountId: storage.outputs.accountId
    keyVaultId: keyvault.outputs.vaultId
    appInsightsId: monitoring.outputs.appInsightsId
    agentIdentityId: identity.outputs.agentIdentityId
    agentIdentityPrincipalId: identity.outputs.agentIdentityPrincipalId
  }
}

// ---------------------------------------------------------------------------
// Bot Service — gated behind deployBotService + spike resolution
// ---------------------------------------------------------------------------

module bot 'modules/bot.bicep' = if (deployBotService) {
  scope: rg
  name: 'bot'
  params: {
    tags: tags
    botServiceName: 'bot-intake-${environmentName}'
  }
}

// ---------------------------------------------------------------------------
// Outputs — consumed by azd and service environment mappings
// ---------------------------------------------------------------------------

output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = subscription().tenantId
output AZURE_RESOURCE_GROUP string = rg.name

output AZURE_COSMOS_ENDPOINT string = cosmos.outputs.endpoint
output AZURE_COSMOS_DATABASE string = cosmos.outputs.databaseName
output AZURE_COSMOS_ACCOUNT_NAME string = cosmos.outputs.accountName

output AZURE_SERVICEBUS_NAMESPACE string = servicebus.outputs.namespaceFqdn
output AZURE_SERVICEBUS_QUEUE string = servicebus.outputs.queueName

output AZURE_STORAGE_ACCOUNT_NAME string = storage.outputs.accountName
output AZURE_STORAGE_BLOB_ENDPOINT string = storage.outputs.blobEndpoint
output AZURE_STORAGE_ARTIFACTS_CONTAINER string = storage.outputs.artifactsContainer

output AZURE_KEYVAULT_URI string = keyvault.outputs.vaultUri
output AZURE_KEYVAULT_NAME string = keyvault.outputs.vaultName

output AZURE_SEARCH_ENDPOINT string = search.outputs.endpoint
output AZURE_SEARCH_SERVICE_NAME string = search.outputs.serviceName

output AZURE_APPINSIGHTS_CONNECTION_STRING string = monitoring.outputs.appInsightsConnectionString
output AZURE_LOG_ANALYTICS_WORKSPACE_ID string = monitoring.outputs.logAnalyticsId

output AZURE_FUNCTIONS_APP_NAME string = functions.outputs.appName

output AGENT_IDENTITY_CLIENT_ID string = identity.outputs.agentIdentityClientId
output WORKER_IDENTITY_CLIENT_ID string = identity.outputs.workerIdentityClientId
output EVAL_IDENTITY_CLIENT_ID string = identity.outputs.evalIdentityClientId

#disable-next-line BCP318
output AZURE_FOUNDRY_HUB_NAME string = deployFoundry ? foundry.outputs.hubName : ''
#disable-next-line BCP318
output AZURE_FOUNDRY_PROJECT_NAME string = deployFoundry ? foundry.outputs.projectName : ''
#disable-next-line BCP318
output AZURE_AI_SERVICES_ENDPOINT string = deployFoundry ? foundry.outputs.aiServicesEndpoint : ''
