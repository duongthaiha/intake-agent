// Microsoft Foundry — private Standard Agent setup using existing project data services.
// Current Foundry resources are Cognitive Services AIServices accounts/projects.
targetScope = 'resourceGroup'

param location string
param tags object
param accountName string
param projectName string
param modelDeploymentName string
param modelName string
param modelVersion string
param modelFormat string = 'OpenAI'
param modelSkuName string = 'GlobalStandard'
param modelCapacity int = 10

param storageAccountName string
param storageAccountId string
param storageBlobEndpoint string
param cosmosAccountName string
param cosmosAccountId string
param cosmosEndpoint string
param searchServiceName string
param searchServiceId string
param searchEndpoint string

param agentSubnetId string
param deployerPrincipalId string = ''

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' existing = {
  name: cosmosAccountName
}

resource searchService 'Microsoft.Search/searchServices@2024-06-01-preview' existing = {
  name: searchServiceName
}

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: accountName
    disableLocalAuth: true
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
      ipRules: []
      virtualNetworkRules: []
    }
    networkInjections: [
      {
        scenario: 'agent'
        subnetArmId: agentSubnetId
        useMicrosoftManagedNetwork: false
      }
    ]
  }
}

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundryAccount
  name: modelDeploymentName
  sku: {
    name: modelSkuName
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: modelFormat
      name: modelName
      version: modelVersion
    }
  }
}

resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundryAccount
  name: projectName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'Intake Agent'
    description: 'Private Microsoft Foundry project for the intake-agent hosted agent.'
  }
  dependsOn: [
    modelDeployment
  ]
}

resource cosmosConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: foundryProject
  name: cosmosAccountName
  properties: {
    category: 'CosmosDB'
    target: cosmosEndpoint
    authType: 'AAD'
    metadata: {
      ApiType: 'Azure'
      ResourceId: cosmosAccountId
      location: cosmosAccount.location
    }
  }
}

resource storageConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: foundryProject
  name: storageAccountName
  properties: {
    category: 'AzureStorageAccount'
    target: storageBlobEndpoint
    authType: 'AAD'
    metadata: {
      ApiType: 'Azure'
      ResourceId: storageAccountId
      location: storageAccount.location
    }
  }
}

resource searchConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: foundryProject
  name: searchServiceName
  properties: {
    category: 'CognitiveSearch'
    target: searchEndpoint
    authType: 'AAD'
    metadata: {
      ApiType: 'Azure'
      ResourceId: searchServiceId
      location: searchService.location
    }
  }
}

var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageBlobDataOwnerRoleId = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
var cosmosDbOperatorRoleId = '230815da-be43-4aae-9cb4-875f7bd000aa'
var searchIndexDataContributorRoleId = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
var searchServiceContributorRoleId = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
var foundryUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'

resource projectStorageContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, foundryProject.id, storageBlobDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: foundryProject.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource projectCosmosOperator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(cosmosAccount.id, foundryProject.id, cosmosDbOperatorRoleId)
  scope: cosmosAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cosmosDbOperatorRoleId)
    principalId: foundryProject.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource projectSearchIndexContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(searchService.id, foundryProject.id, searchIndexDataContributorRoleId)
  scope: searchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributorRoleId)
    principalId: foundryProject.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource projectSearchServiceContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(searchService.id, foundryProject.id, searchServiceContributorRoleId)
  scope: searchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributorRoleId)
    principalId: foundryProject.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource deployerFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  name: guid(foundryProject.id, deployerPrincipalId, foundryUserRoleId)
  scope: foundryProject
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUserRoleId)
    principalId: deployerPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource projectCapabilityHost 'Microsoft.CognitiveServices/accounts/projects/capabilityHosts@2025-06-01' = {
  parent: foundryProject
  name: 'agents'
  properties: {
    #disable-next-line BCP037
    capabilityHostKind: 'Agents'
    storageConnections: [
      storageConnection.name
    ]
    threadStorageConnections: [
      cosmosConnection.name
    ]
    vectorStoreConnections: [
      searchConnection.name
    ]
  }
  dependsOn: [
    projectStorageContributor
    projectCosmosOperator
    projectSearchIndexContributor
    projectSearchServiceContributor
  ]
}

resource projectStorageOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, foundryProject.id, storageBlobDataOwnerRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataOwnerRoleId)
    principalId: foundryProject.identity.principalId
    principalType: 'ServicePrincipal'
  }
  dependsOn: [
    projectCapabilityHost
  ]
}

var cosmosDataContributorRoleDefinitionId = '${cosmosAccount.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'

resource projectCosmosDataContributor 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmosAccount
  name: guid(cosmosAccount.id, foundryProject.id, 'enterprise-memory')
  properties: {
    roleDefinitionId: cosmosDataContributorRoleDefinitionId
    principalId: foundryProject.identity.principalId
    scope: '${cosmosAccount.id}/dbs/enterprise_memory'
  }
  dependsOn: [
    projectCapabilityHost
  ]
}

output accountId string = foundryAccount.id
output accountName string = foundryAccount.name
output accountEndpoint string = foundryAccount.properties.endpoint
output projectId string = foundryProject.id
output projectName string = foundryProject.name
output projectEndpoint string = 'https://${foundryAccount.name}.services.ai.azure.com/api/projects/${foundryProject.name}'
output projectPrincipalId string = foundryProject.identity.principalId
output modelDeploymentName string = modelDeployment.name
