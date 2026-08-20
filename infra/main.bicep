targetScope = 'subscription'

@description('Short environment identifier.')
@allowed([
  'dev'
  'test'
  'prod'
])
param environmentName string

@description('Primary Azure region. eastus2 is the current candidate and must be revalidated before provisioning.')
param location string = 'eastus2'

@description('Azure AI Search region. Override when the primary region has no Search capacity.')
param searchLocation string = location

@description('Foundry ingress topology. Customer data services remain private in both modes.')
@allowed([
  'baseline'
  'hardened'
])
param networkMode string = 'hardened'

@description('Resource group name.')
param resourceGroupName string = 'rg-intake-${environmentName}'

@description('Deployment owner tag.')
param owner string = 'intake-agent-team'

@description('Cost center tag.')
param costCenter string = 'unassigned'

@description('Deploy runtime workloads after immutable container images are available.')
param deployWorkloads bool = false

@description('Immutable command-service image in the private ACR.')
param commandServiceImage string = 'runtime-artifact-required'

@description('Immutable worker image in the private ACR.')
param workersImage string = 'runtime-artifact-required'

@description('Immutable evaluation image in the private ACR.')
param evaluationImage string = 'runtime-artifact-required'

@minValue(400)
@description('Autoscale maximum RU/s for the product Cosmos database.')
param cosmosMaxThroughput int = 4000

@minValue(1)
@description('Monthly resource-group budget in the billing currency.')
param monthlyBudgetAmount int = 500

@description('Budget start date, formatted as the first day of a month.')
param budgetStartDate string = '2026-08-01'

@description('Optional Azure Policy definition resource IDs assigned to the environment resource group.')
param policyDefinitionIds array = []

var hardened = networkMode == 'hardened'
var production = environmentName == 'prod'
var uniqueSuffix = take(uniqueString(subscription().id, environmentName, location), 6)
var suffix = '${environmentName}-${uniqueSuffix}'
var tags = {
  application: 'intake-agent'
  environment: environmentName
  owner: owner
  costCenter: costCenter
  managedBy: 'bicep-azd'
  networkMode: networkMode
  dataClassification: 'confidential'
}

resource applicationResourceGroup 'Microsoft.Resources/resourceGroups@2024-11-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module network 'modules/network.bicep' = {
  name: 'network'
  scope: applicationResourceGroup
  params: {
    location: location
    suffix: suffix
    tags: tags
  }
}

module identity 'modules/identity.bicep' = {
  name: 'identity'
  scope: applicationResourceGroup
  params: {
    location: location
    suffix: suffix
    tags: tags
  }
}

module egress 'modules/egress.bicep' = if (hardened) {
  name: 'controlled-egress'
  scope: applicationResourceGroup
  params: {
    firewallSubnetId: network.outputs.firewallSubnetId
    location: location
    suffix: suffix
    tags: tags
  }
}

module networkRoutes 'modules/network-routes.bicep' = if (hardened) {
  name: 'controlled-egress-routes'
  scope: applicationResourceGroup
  params: {
    containerAppsNetworkSecurityGroupId: network.outputs.containerAppsNetworkSecurityGroupId
    foundryNetworkSecurityGroupId: network.outputs.foundryNetworkSecurityGroupId
    functionsNetworkSecurityGroupId: network.outputs.functionsNetworkSecurityGroupId
    routeTableId: egress!.outputs.routeTableId
    virtualNetworkName: network.outputs.virtualNetworkName
  }
}

module observability 'modules/observability.bicep' = {
  name: 'observability'
  scope: applicationResourceGroup
  params: {
    hardened: hardened
    location: location
    retentionInDays: production ? 180 : 90
    suffix: suffix
    tags: tags
  }
}

module data 'modules/data.bicep' = {
  name: 'data'
  scope: applicationResourceGroup
  params: {
    cosmosMaxThroughput: cosmosMaxThroughput
    location: location
    searchLocation: searchLocation
    suffix: suffix
    tags: tags
    workspaceId: observability.outputs.workspaceId
    zoneRedundant: production
  }
}

module containerEnvironment 'modules/container-environment.bicep' = {
  name: 'container-environment'
  scope: applicationResourceGroup
  params: {
    infrastructureSubnetId: network.outputs.containerAppsSubnetId
    location: location
    suffix: suffix
    tags: tags
    workspaceCustomerId: observability.outputs.workspaceCustomerId
    workspaceId: observability.outputs.workspaceId
    workspaceSharedKey: observability.outputs.workspaceSharedKey
    zoneRedundant: production
  }
  dependsOn: [
    networkRoutes
    privateEndpoints
  ]
}

module foundry 'modules/foundry.bicep' = {
  name: 'foundry'
  scope: applicationResourceGroup
  params: {
    cosmos: data.outputs.foundryCosmos
    foundrySubnetId: network.outputs.foundrySubnetId
    hardened: hardened
    location: location
    search: data.outputs.search
    storage: data.outputs.foundryStorage
    suffix: suffix
    tags: tags
    workspaceId: observability.outputs.workspaceId
  }
  dependsOn: [
    networkRoutes
  ]
}

module privateEndpoints 'modules/private-endpoints.bicep' = {
  name: 'private-endpoints'
  scope: applicationResourceGroup
  params: {
    location: location
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    suffix: suffix
    tags: tags
    targets: {
      cosmos: data.outputs.cosmos.id
      foundryCosmos: data.outputs.foundryCosmos.id
      foundryStorage: data.outputs.foundryStorage.id
      foundry: foundry.outputs.foundry.accountId
      keyVault: data.outputs.keyVault.id
      monitorPrivateLinkScope: observability.outputs.privateLinkScopeId
      registry: data.outputs.registry.id
      search: data.outputs.search.id
      serviceBus: data.outputs.serviceBus.id
      storage: data.outputs.storage.id
    }
    virtualNetworkId: network.outputs.virtualNetworkId
  }
}

module rbac 'modules/rbac.bicep' = {
  name: 'rbac'
  scope: applicationResourceGroup
  params: {
    foundryProjectPrincipalId: foundry.outputs.foundry.projectPrincipalId
    foundryAccountName: foundry.outputs.foundry.accountName
    foundryProjectName: foundry.outputs.foundry.projectName
    identities: identity.outputs.identities
    resources: {
      cosmosName: data.outputs.cosmos.name
      foundryCosmosName: data.outputs.foundryCosmos.name
      foundryStorageName: data.outputs.foundryStorage.name
      keyVaultName: data.outputs.keyVault.name
      registryName: data.outputs.registry.name
      searchName: data.outputs.search.name
      serviceBusName: data.outputs.serviceBus.name
      storageName: data.outputs.storage.name
      applicationInsightsName: observability.outputs.applicationInsightsName
    }
  }
}

module foundryCapabilityHost 'modules/foundry-capability-host.bicep' = {
  name: 'foundry-capability-host'
  scope: applicationResourceGroup
  params: {
    accountName: foundry.outputs.foundry.accountName
    connectionNames: foundry.outputs.foundry.connectionNames
    projectName: foundry.outputs.foundry.projectName
  }
  dependsOn: [
    privateEndpoints
    rbac
  ]
}

module compute 'modules/compute.bicep' = {
  name: 'compute'
  scope: applicationResourceGroup
  params: {
    commandServiceImage: commandServiceImage
    configuration: {
      applicationInsightsConnectionString: observability.outputs.applicationInsightsConnectionString
      cosmosDatabase: data.outputs.cosmos.databaseName
      cosmosEndpoint: data.outputs.cosmos.endpoint
      foundryProjectEndpoint: 'https://${foundry.outputs.foundry.accountName}.services.ai.azure.com/api/projects/${foundry.outputs.foundry.projectName}'
      keyVaultUri: data.outputs.keyVault.uri
      serviceBusNamespace: data.outputs.serviceBus.name
      serviceBusTopic: data.outputs.serviceBus.topicName
      storageAccountName: data.outputs.storage.name
    }
    deployWorkloads: deployWorkloads
    environment: containerEnvironment.outputs.environment
    evaluationImage: evaluationImage
    identities: identity.outputs.identities
    location: location
    registry: data.outputs.registry
    suffix: suffix
    tags: tags
    workersImage: workersImage
  }
  dependsOn: [
    foundryCapabilityHost
  ]
}

module governance 'modules/governance.bicep' = {
  name: 'governance'
  scope: applicationResourceGroup
  params: {
    budgetStartDate: budgetStartDate
    enableDeleteLock: production
    monthlyBudgetAmount: monthlyBudgetAmount
    policyDefinitionIds: policyDefinitionIds
    tags: tags
  }
  dependsOn: [
    compute
  ]
}

output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = applicationResourceGroup.name
output AZURE_NETWORK_MODE string = networkMode
output AZURE_CONTAINER_APPS_ENVIRONMENT_ID string = containerEnvironment.outputs.environment.id
output AZURE_CONTAINER_APPS_ENVIRONMENT_NAME string = containerEnvironment.outputs.environment.name
output AZURE_VIRTUAL_NETWORK_ID string = network.outputs.virtualNetworkId
output AZURE_CONTAINER_REGISTRY_ID string = data.outputs.registry.id
output AZURE_CONTAINER_REGISTRY_NAME string = data.outputs.registry.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = data.outputs.registry.loginServer
output AZURE_COSMOS_ENDPOINT string = data.outputs.cosmos.endpoint
output AZURE_COSMOS_DATABASE string = data.outputs.cosmos.databaseName
output AZURE_STORAGE_ACCOUNT_NAME string = data.outputs.storage.name
output AZURE_SEARCH_ENDPOINT string = data.outputs.search.endpoint
output AZURE_SERVICE_BUS_NAMESPACE string = data.outputs.serviceBus.name
output AZURE_SERVICE_BUS_TOPIC string = data.outputs.serviceBus.topicName
output AZURE_KEY_VAULT_URI string = data.outputs.keyVault.uri
output AZURE_APPLICATION_INSIGHTS_CONNECTION_STRING string = observability.outputs.applicationInsightsConnectionString
output AZURE_FOUNDRY_ACCOUNT_ID string = foundry.outputs.foundry.accountId
output AZURE_FOUNDRY_ACCOUNT_NAME string = foundry.outputs.foundry.accountName
output AZURE_FOUNDRY_PROJECT_ID string = foundry.outputs.foundry.projectId
output AZURE_FOUNDRY_PROJECT_NAME string = foundry.outputs.foundry.projectName
output AZURE_FOUNDRY_PROJECT_ENDPOINT string = 'https://${foundry.outputs.foundry.accountName}.services.ai.azure.com/api/projects/${foundry.outputs.foundry.projectName}'
output AZURE_FOUNDRY_COSMOS_CONNECTION string = foundry.outputs.foundry.connectionNames.cosmos
output AZURE_FOUNDRY_STORAGE_CONNECTION string = foundry.outputs.foundry.connectionNames.storage
output AZURE_FOUNDRY_SEARCH_CONNECTION string = foundry.outputs.foundry.connectionNames.search
output AZURE_COMMAND_SERVICE_NAME string = compute.outputs.workloadResourceNames.commandService
output AZURE_OUTBOX_WORKER_NAME string = compute.outputs.workloadResourceNames.workers.outbox
output AZURE_NOTIFICATION_WORKER_NAME string = compute.outputs.workloadResourceNames.workers.notification
output AZURE_INTEGRATION_WORKER_NAME string = compute.outputs.workloadResourceNames.workers.integration
output AZURE_COMPLETION_WORKER_NAME string = compute.outputs.workloadResourceNames.workers.completion
output AZURE_RETENTION_WORKER_NAME string = compute.outputs.workloadResourceNames.workers.retention
output AZURE_EVALUATION_JOB_NAME string = compute.outputs.workloadResourceNames.evaluationJob
