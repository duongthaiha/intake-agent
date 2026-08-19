// intake-agent — Main Bicep orchestrator
// Scope: existing resource group. Deploy via: azd provision.
// The resource group is deliberately created out-of-band so the OIDC deployer
// needs permissions only on rg-intake-dev, not across the subscription.
targetScope = 'resourceGroup'

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

@minLength(1)
@description('Object ID of the federated service principal running azd. Set AZURE_PRINCIPAL_ID; it is never inferred from an interactive user.')
param principalId string

@description('Deploy Azure Bot Service resource. Requires Microsoft.BotService provider registered + Teams publishing spike resolved.')
param deployBotService bool = false

@minLength(1)
@description('Application (client) ID of the tenant-scoped MCP server app registration. Bootstrap it before azd provision.')
param mcpServerAppClientId string

@minLength(1)
@description('Name of the secure custom OAuth connection created in the Foundry project.')
param mcpOAuthConnectionName string

@minLength(1)
@description('Versioned Foundry Toolbox name that exposes the MCP tools.')
param mcpToolboxName string

@minLength(1)
@description('Foundry Toolbox MCP server label used to namespace requester tool names.')
param mcpToolboxServerLabel string

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

// Private endpoints are not a toggle any more, they are the architecture.
// Every data service below is publicNetworkAccess:Disabled with deny-by-default
// ACLs, and the deployment pipeline reaches their data planes only from inside
// the VNet. A `deployPrivateEndpoints=false` steady state would leave those
// ACLs denying everything from a public path — an unsupported, internally
// contradictory configuration — so the parameter is gone rather than
// defaulted: ARM rejects the deployment outright if a caller still passes it.
var deployPrivateEndpoints = true

// Stable 13-char token scoped to subscription + environment + location.
// Used as suffix for globally-unique resource names (storage, KV).
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))

var resourceGroupName = resourceGroup().name

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
// Monitoring — Log Analytics + Application Insights
// ---------------------------------------------------------------------------

module monitoring 'modules/monitoring.bicep' = {
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
  name: 'network'
  params: {
    location: location
    tags: tags
    vnetName: 'vnet-intake-${environmentName}'
    deployPrivateEndpoints: deployPrivateEndpoints
    deployStoragePrivateEndpoint: true
    cosmosAccountName: cosmosAccountName
    storageAccountName: storageAccountName
    searchServiceName: searchServiceName
    keyVaultName: keyVaultName
  }
}

// ---------------------------------------------------------------------------
// Managed identities
// ---------------------------------------------------------------------------

module identity 'modules/identity.bicep' = {
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
  name: 'keyvault'
  params: {
    location: location
    tags: tags
    keyVaultName: 'kv-${take(resourceToken, 16)}'
    workerIdentityPrincipalId: identity.outputs.workerIdentityPrincipalId
    deployerPrincipalId: principalId
  }
}

// ---------------------------------------------------------------------------
// Storage account
// ---------------------------------------------------------------------------

module storage 'modules/storage.bicep' = {
  name: 'storage'
  params: {
    location: location
    tags: tags
    storageAccountName: 'st${take(resourceToken, 10)}'
    workerIdentityPrincipalId: identity.outputs.workerIdentityPrincipalId
    evalIdentityPrincipalId: identity.outputs.evalIdentityPrincipalId
    functionsMIPrincipalId: identity.outputs.workerIdentityPrincipalId
    mcpIdentityPrincipalId: identity.outputs.mcpIdentityPrincipalId
    functionsSubnetId: functionsSubnetId
  }
  dependsOn: [network]
}

// ---------------------------------------------------------------------------
// Cosmos DB
// ---------------------------------------------------------------------------

module cosmos 'modules/cosmos.bicep' = {
  name: 'cosmos'
  params: {
    location: location
    tags: tags
    accountName: 'cosmos-${take(resourceToken, 10)}'
    deployPrivateEndpoints: deployPrivateEndpoints
    mcpIdentityPrincipalId: identity.outputs.mcpIdentityPrincipalId
    workerIdentityPrincipalId: identity.outputs.workerIdentityPrincipalId
  }
}

// ---------------------------------------------------------------------------
// Service Bus
// ---------------------------------------------------------------------------

module servicebus 'modules/servicebus.bicep' = {
  name: 'servicebus'
  params: {
    location: location
    tags: tags
    namespaceName: serviceBusName
    mcpIdentityPrincipalId: identity.outputs.mcpIdentityPrincipalId
    workerIdentityPrincipalId: identity.outputs.workerIdentityPrincipalId
  }
}

// ---------------------------------------------------------------------------
// AI Search
// ---------------------------------------------------------------------------

module search 'modules/search.bicep' = {
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
    cosmosRequestsContainer: cosmos.outputs.requestsContainerName
    cosmosTemplatesContainer: cosmos.outputs.templatesContainerName
    cosmosIdempotencyContainer: cosmos.outputs.idempotencyContainerName
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
    mcpIdentityId: identity.outputs.mcpIdentityId
    mcpIdentityClientId: identity.outputs.mcpIdentityClientId
    storageEndpoint: storage.outputs.blobEndpoint
    evalContainer: storage.outputs.evalContainer
    cosmosEndpoint: cosmos.outputs.endpoint
    cosmosDatabase: cosmos.outputs.databaseName
    cosmosRequestsContainer: cosmos.outputs.requestsContainerName
    cosmosTemplatesContainer: cosmos.outputs.templatesContainerName
    cosmosIdempotencyContainer: cosmos.outputs.idempotencyContainerName
    serviceBusNamespace: servicebus.outputs.namespaceFqdn
    serviceBusQueue: servicebus.outputs.queueName
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    mcpAudience: mcpServerAppClientId
    mcpScope: 'Intake.Tools.ReadWrite'
    tenantId: subscription().tenantId
    subnetId: network.outputs.containerAppsSubnetId
    environmentNameTag: environmentName
  }
}

// ---------------------------------------------------------------------------
// Azure AI Foundry (hub + project + AI Services) — always deployed
// ---------------------------------------------------------------------------

module foundry 'modules/foundry.bicep' = {
  name: 'foundry'
  params: {
    location: location
    tags: tags
    accountName: 'ais-intake-${take(resourceToken, 8)}'
    projectName: 'aiproj-intake-${environmentName}'
    modelDeploymentName: 'gpt-5-nano'
    modelName: 'gpt-5-nano'
    modelVersion: '2025-08-07'
    modelFormat: 'OpenAI'
    modelSkuName: 'GlobalStandard'
    modelCapacity: 10
    storageAccountName: storage.outputs.accountName
    storageAccountId: storage.outputs.accountId
    storageBlobEndpoint: storage.outputs.blobEndpoint
    cosmosAccountName: cosmos.outputs.accountName
    cosmosAccountId: cosmos.outputs.accountId
    cosmosEndpoint: cosmos.outputs.endpoint
    searchServiceName: search.outputs.serviceName
    searchServiceId: search.outputs.serviceId
    searchEndpoint: search.outputs.endpoint
    agentSubnetId: network.outputs.foundryAgentSubnetId
    deployerPrincipalId: principalId
  }
}

module foundryPrivateEndpoint 'modules/foundry-private-endpoint.bicep' = {
  name: 'foundryPrivateEndpoint'
  params: {
    location: location
    tags: tags
    accountName: foundry.outputs.accountName
    accountId: foundry.outputs.accountId
    privateEndpointSubnetId: network.outputs.peSubnetId
    foundryPrivateDnsZoneIds: [
      network.outputs.foundryServicesPrivateDnsZoneId
      network.outputs.foundryOpenAiPrivateDnsZoneId
      network.outputs.foundryCognitiveServicesPrivateDnsZoneId
    ]
  }
}

// ---------------------------------------------------------------------------
// Bot Service — gated behind deployBotService + spike resolution
// ---------------------------------------------------------------------------

module bot 'modules/bot.bicep' = if (deployBotService) {
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
output AZURE_RESOURCE_GROUP string = resourceGroupName

output AZURE_COSMOS_ENDPOINT string = cosmos.outputs.endpoint
output AZURE_COSMOS_DATABASE string = cosmos.outputs.databaseName
output AZURE_COSMOS_ACCOUNT_NAME string = cosmos.outputs.accountName
output AZURE_COSMOS_REQUESTS_CONTAINER string = cosmos.outputs.requestsContainerName
output AZURE_COSMOS_TEMPLATES_CONTAINER string = cosmos.outputs.templatesContainerName
output AZURE_COSMOS_IDEMPOTENCY_CONTAINER string = cosmos.outputs.idempotencyContainerName

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
output AGENT_RUNTIME_PRINCIPAL_ID string = identity.outputs.agentIdentityPrincipalId
output MCP_IDENTITY_CLIENT_ID string = identity.outputs.mcpIdentityClientId
output MCP_RUNTIME_PRINCIPAL_ID string = identity.outputs.mcpIdentityPrincipalId

output INTAKE_MCP_ENDPOINT string = containerApps.outputs.mcpEndpoint
output INTAKE_MCP_FQDN string = containerApps.outputs.mcpFqdn
output INTAKE_MCP_AUDIENCE string = mcpServerAppClientId
output INTAKE_MCP_REQUIRED_SCOPE string = 'Intake.Tools.ReadWrite'
output AZURE_MCP_CONTAINER_APP_NAME string = containerApps.outputs.mcpAppName
output MCP_OAUTH_CONNECTION_NAME string = mcpOAuthConnectionName
output MCP_TOOLBOX_NAME string = mcpToolboxName
output MCP_TOOLBOX_SERVER_LABEL string = mcpToolboxServerLabel

output AZURE_FOUNDRY_HUB_NAME string = foundry.outputs.accountName
output AZURE_FOUNDRY_PROJECT_NAME string = foundry.outputs.projectName
output AZURE_AI_SERVICES_ENDPOINT string = foundry.outputs.accountEndpoint
output AZURE_AI_ACCOUNT_NAME string = foundry.outputs.accountName
output AZURE_AI_PROJECT_NAME string = foundry.outputs.projectName
output AZURE_AI_PROJECT_ID string = foundry.outputs.projectId
output AZURE_AI_PROJECT_ENDPOINT string = foundry.outputs.projectEndpoint
output FOUNDRY_PROJECT_ENDPOINT string = foundry.outputs.projectEndpoint
output AZURE_AI_MODEL_DEPLOYMENT_NAME string = foundry.outputs.modelDeploymentName
