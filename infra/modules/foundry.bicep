@description('Azure region for Microsoft Foundry resources.')
param location string

@description('Short, globally consistent resource-name suffix.')
param suffix string

@description('Common resource tags.')
param tags object

@description('Disable public Foundry ingress while retaining private ingress.')
param hardened bool = true

@description('Dedicated /24 subnet for Foundry hosted-agent network injection.')
param foundrySubnetId string

@description('Customer-owned storage account.')
param storage object

@description('Customer-owned Cosmos DB account.')
param cosmos object

@description('Customer-owned Azure AI Search service.')
param search object

@description('Log Analytics workspace resource ID for diagnostic settings.')
param workspaceId string

var accountName = take('ai-intake-${suffix}', 64)
var projectName = take('intake-${suffix}', 64)

resource account 'Microsoft.CognitiveServices/accounts@2026-05-01' = {
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
    allowedFqdnList: hardened
      ? [
          'graph.microsoft.com'
          replace(replace(environment().authentication.loginEndpoint, 'https://', ''), '/', '')
          replace(replace(environment().resourceManager, 'https://', ''), '/', '')
        ]
      : []
    allowProjectManagement: true
    customSubDomainName: accountName
    disableLocalAuth: true
    dynamicThrottlingEnabled: true
    networkAcls: {
      bypass: 'None'
      defaultAction: 'Deny'
      ipRules: []
      virtualNetworkRules: []
    }
    networkInjections: [
      {
        scenario: 'agent'
        subnetArmId: foundrySubnetId
        useMicrosoftManagedNetwork: false
      }
    ]
    publicNetworkAccess: hardened ? 'Disabled' : 'Enabled'
    restrictOutboundNetworkAccess: hardened
    userOwnedStorage: [
      {
        resourceId: storage.id
      }
    ]
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2026-05-01' = {
  parent: account
  name: projectName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    description: 'Microsoft Foundry project for the Intake Agent MVP.'
    displayName: 'Intake Agent ${suffix}'
  }
}

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: account
  name: 'gpt-4.1-mini'
  sku: {
    name: 'DataZoneStandard'
    capacity: 10
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4.1-mini'
      version: '2025-04-14'
    }
    raiPolicyName: 'Microsoft.DefaultV2'
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
}

resource cosmosConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2026-05-01' = {
  parent: project
  name: 'intake-cosmos'
  properties: {
    authType: 'AAD'
    category: 'CosmosDB'
    target: cosmos.endpoint
    metadata: {
      ApiType: 'Azure'
      ResourceId: cosmos.id
      location: location
    }
  }
}

resource storageConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2026-05-01' = {
  parent: project
  name: 'intake-storage'
  properties: {
    authType: 'AAD'
    category: 'AzureStorageAccount'
    target: storage.blobEndpoint
    metadata: {
      ApiType: 'Azure'
      ResourceId: storage.id
      location: location
    }
  }
}

resource searchConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2026-05-01' = {
  parent: project
  name: 'intake-search'
  properties: {
    authType: 'AAD'
    category: 'CognitiveSearch'
    target: search.endpoint
    metadata: {
      ApiType: 'Azure'
      ResourceId: search.id
      location: location
    }
  }
}

resource accountDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'send-to-log-analytics'
  scope: account
  properties: {
    workspaceId: workspaceId
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

output foundry object = {
  accountId: account.id
  accountName: account.name
  accountEndpoint: account.properties.endpoint
  projectId: project.id
  projectName: project.name
  projectPrincipalId: project.identity.principalId
  modelDeploymentName: modelDeployment.name
  connectionNames: {
    cosmos: cosmosConnection.name
    storage: storageConnection.name
    search: searchConnection.name
  }
}
