@description('Names of data resources.')
param resources object

@description('Managed workload identities.')
param identities object

@description('Microsoft Foundry project managed identity principal ID.')
param foundryProjectPrincipalId string

@description('Microsoft Foundry account name.')
param foundryAccountName string

@description('Microsoft Foundry project name.')
param foundryProjectName string

var storageBlobDataContributor = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
var storageBlobDataOwner = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b')
var storageAccountContributor = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '17d1049b-9a84-46fb-8f53-869881c3d3ab')
var acrPull = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
var serviceBusDataSender = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39')
var serviceBusDataReceiver = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0')
var keyVaultSecretsUser = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
var cosmosDbOperator = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '230815da-be43-4aae-9cb4-875f7bd000aa')
var searchIndexDataContributor = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '8ebe5a00-799e-43f5-93ac-243d3dce84a7')
var searchServiceContributor = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7ca78c08-252a-4471-8644-bb5ff32d4ba0')
var searchIndexDataReader = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '1407120a-92aa-4202-b7e9-c0e197c71c8f')
var monitoringMetricsPublisher = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '3913510d-42f4-4e42-8a64-420c390055eb')
var foundryUser = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')

resource storage 'Microsoft.Storage/storageAccounts@2026-04-01' existing = {
  name: resources.storageName
}

resource foundryStorage 'Microsoft.Storage/storageAccounts@2026-04-01' existing = {
  name: resources.foundryStorageName
}

resource registry 'Microsoft.ContainerRegistry/registries@2025-04-01' existing = {
  name: resources.registryName
}

resource serviceBus 'Microsoft.ServiceBus/namespaces@2026-01-01' existing = {
  name: resources.serviceBusName
}

resource keyVault 'Microsoft.KeyVault/vaults@2026-02-01' existing = {
  name: resources.keyVaultName
}

resource search 'Microsoft.Search/searchServices@2025-05-01' existing = {
  name: resources.searchName
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2026-03-15' existing = {
  name: resources.cosmosName
}

resource foundryCosmos 'Microsoft.DocumentDB/databaseAccounts@2026-03-15' existing = {
  name: resources.foundryCosmosName
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: resources.applicationInsightsName
}

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2026-05-01' existing = {
  name: foundryAccountName
}

resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2026-05-01' existing = {
  parent: foundryAccount
  name: foundryProjectName
}

var allWorkloadPrincipals = [
  identities.commandService.principalId
  identities.outboxWorker.principalId
  identities.notificationWorker.principalId
  identities.integrationWorker.principalId
  identities.completionWorker.principalId
  identities.retentionWorker.principalId
  identities.evaluationJob.principalId
]

resource acrPullAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for principalId in allWorkloadPrincipals: {
    name: guid(registry.id, principalId, acrPull)
    scope: registry
    properties: {
      principalId: principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: acrPull
    }
  }
]

var storageContributors = [
  identities.retentionWorker.principalId
  identities.evaluationJob.principalId
]

resource foundryStorageBlobOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryStorage.id, foundryProjectPrincipalId, storageBlobDataOwner)
  scope: foundryStorage
  properties: {
    principalId: foundryProjectPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: storageBlobDataOwner
  }
}

resource foundryStorageAccountContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryStorage.id, foundryProjectPrincipalId, storageAccountContributor)
  scope: foundryStorage
  properties: {
    principalId: foundryProjectPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: storageAccountContributor
  }
}

resource storageAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for principalId in storageContributors: {
    name: guid(storage.id, principalId, storageBlobDataContributor)
    scope: storage
    properties: {
      principalId: principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: storageBlobDataContributor
    }
  }
]

var serviceBusSenders = [
  identities.commandService.principalId
  identities.outboxWorker.principalId
]

resource serviceBusSenderAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for principalId in serviceBusSenders: {
    name: guid(serviceBus.id, principalId, serviceBusDataSender)
    scope: serviceBus
    properties: {
      principalId: principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: serviceBusDataSender
    }
  }
]

var serviceBusReceivers = [
  identities.notificationWorker.principalId
  identities.integrationWorker.principalId
  identities.completionWorker.principalId
  identities.retentionWorker.principalId
]

resource serviceBusReceiverAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for principalId in serviceBusReceivers: {
    name: guid(serviceBus.id, principalId, serviceBusDataReceiver)
    scope: serviceBus
    properties: {
      principalId: principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: serviceBusDataReceiver
    }
  }
]

var keyVaultReaders = [
  identities.notificationWorker.principalId
  identities.integrationWorker.principalId
  identities.retentionWorker.principalId
]

resource keyVaultAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for principalId in keyVaultReaders: {
    name: guid(keyVault.id, principalId, keyVaultSecretsUser)
    scope: keyVault
    properties: {
      principalId: principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: keyVaultSecretsUser
    }
  }
]

resource foundrySearchContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, foundryProjectPrincipalId, searchServiceContributor)
  scope: search
  properties: {
    principalId: foundryProjectPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: searchServiceContributor
  }
}

resource foundrySearchIndexContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, foundryProjectPrincipalId, searchIndexDataContributor)
  scope: search
  properties: {
    principalId: foundryProjectPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: searchIndexDataContributor
  }
}

resource foundryCosmosOperator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryCosmos.id, foundryProjectPrincipalId, cosmosDbOperator)
  scope: foundryCosmos
  properties: {
    principalId: foundryProjectPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: cosmosDbOperator
  }
}

resource evaluationFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryProject.id, identities.evaluationJob.principalId, foundryUser)
  scope: foundryProject
  properties: {
    principalId: identities.evaluationJob.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: foundryUser
  }
}

resource telemetryPublishers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for principalId in allWorkloadPrincipals: {
    name: guid(applicationInsights.id, principalId, monitoringMetricsPublisher)
    scope: applicationInsights
    properties: {
      principalId: principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: monitoringMetricsPublisher
    }
  }
]

resource evaluationSearchReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, identities.evaluationJob.principalId, searchIndexDataReader)
  scope: search
  properties: {
    principalId: identities.evaluationJob.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: searchIndexDataReader
  }
}

var cosmosContributors = [
  identities.commandService.principalId
  identities.outboxWorker.principalId
  identities.integrationWorker.principalId
  identities.completionWorker.principalId
  identities.retentionWorker.principalId
]

resource cosmosDataAssignments 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = [
  for principalId in cosmosContributors: {
    parent: cosmos
    name: guid(cosmos.id, principalId, '00000000-0000-0000-0000-000000000002')
    properties: {
      principalId: principalId
      roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
      scope: cosmos.id
    }
  }
]

resource foundryCosmosDataAssignment 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: foundryCosmos
  name: guid(foundryCosmos.id, foundryProjectPrincipalId, '00000000-0000-0000-0000-000000000002')
  properties: {
    principalId: foundryProjectPrincipalId
    roleDefinitionId: '${foundryCosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    scope: foundryCosmos.id
  }
}
