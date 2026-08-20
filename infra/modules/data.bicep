@description('Azure region for data and messaging resources.')
param location string

@description('Short, globally consistent resource-name suffix.')
param suffix string

@description('Common resource tags.')
param tags object

@description('Log Analytics workspace resource ID for diagnostic settings.')
param workspaceId string

@description('Enable supported zone redundancy features.')
param zoneRedundant bool = false

@minValue(400)
@description('Autoscale maximum RU/s for the product Cosmos DB database.')
param cosmosMaxThroughput int = 4000

var compactSuffix = toLower(replace(suffix, '-', ''))
var storageName = take('stintake${compactSuffix}', 24)
var foundryStorageName = take('stfoundry${compactSuffix}', 24)
var cosmosName = take('cosmos-intake-${suffix}', 44)
var foundryCosmosName = take('cosmos-foundry-${suffix}', 44)
var searchName = take('srch-intake-${suffix}', 60)
var serviceBusName = take('sb-intake-${suffix}', 50)
var keyVaultName = take('kv-intake-${suffix}', 24)
var registryName = take('acrintake${compactSuffix}', 50)
var databaseName = 'intake'
var topicName = 'domain-events'

resource storage 'Microsoft.Storage/storageAccounts@2026-04-01' = {
  name: storageName
  location: location
  tags: tags
  sku: {
    name: zoneRedundant ? 'Standard_ZRS' : 'Standard_LRS'
  }
  kind: 'StorageV2'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowCrossTenantReplication: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    isHnsEnabled: false
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Disabled'
    supportsHttpsTrafficOnly: true
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
      ipRules: []
      virtualNetworkRules: []
    }
    encryption: {
      keySource: 'Microsoft.Storage'
      requireInfrastructureEncryption: true
      services: {
        blob: {
          enabled: true
          keyType: 'Account'
        }
        file: {
          enabled: true
          keyType: 'Account'
        }
      }
    }
  }
}

resource foundryStorage 'Microsoft.Storage/storageAccounts@2026-04-01' = {
  name: foundryStorageName
  location: location
  tags: union(tags, {
    purpose: 'foundry-agent-state'
  })
  sku: {
    name: zoneRedundant ? 'Standard_ZRS' : 'Standard_LRS'
  }
  kind: 'StorageV2'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowCrossTenantReplication: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Disabled'
    supportsHttpsTrafficOnly: true
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
      ipRules: []
      virtualNetworkRules: []
    }
    encryption: {
      keySource: 'Microsoft.Storage'
      requireInfrastructureEncryption: true
      services: {
        blob: {
          enabled: true
          keyType: 'Account'
        }
        file: {
          enabled: true
          keyType: 'Account'
        }
      }
    }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2025-06-01' = {
  parent: storage
  name: 'default'
  properties: {
    changeFeed: {
      enabled: true
      retentionInDays: 30
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 14
    }
    deleteRetentionPolicy: {
      enabled: true
      days: 14
      allowPermanentDelete: false
    }
    isVersioningEnabled: true
  }
}

var blobContainers = [
  'agent-files'
  'evaluation-datasets'
  'evaluation-evidence'
  'function-packages'
]

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-06-01' = [
  for containerName in blobContainers: {
    parent: blobService
    name: containerName
    properties: {
      publicAccess: 'None'
      immutableStorageWithVersioning: containerName == 'evaluation-evidence'
        ? {
            enabled: true
          }
        : null
    }
  }
]

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2026-03-15' = {
  name: cosmosName
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    databaseAccountOfferType: 'Standard'
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: zoneRedundant
      }
    ]
    backupPolicy: {
      type: 'Continuous'
      continuousModeProperties: {
        tier: 'Continuous7Days'
      }
    }
    disableKeyBasedMetadataWriteAccess: true
    disableLocalAuth: true
    enableAutomaticFailover: false
    enableFreeTier: false
    enableMultipleWriteLocations: false
    isVirtualNetworkFilterEnabled: false
    networkAclBypass: 'None'
    publicNetworkAccess: 'Disabled'
  }
}

resource foundryCosmos 'Microsoft.DocumentDB/databaseAccounts@2026-03-15' = {
  name: foundryCosmosName
  location: location
  tags: union(tags, {
    purpose: 'foundry-agent-state'
  })
  kind: 'GlobalDocumentDB'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    databaseAccountOfferType: 'Standard'
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: zoneRedundant
      }
    ]
    backupPolicy: {
      type: 'Continuous'
      continuousModeProperties: {
        tier: 'Continuous7Days'
      }
    }
    disableKeyBasedMetadataWriteAccess: true
    disableLocalAuth: true
    enableAutomaticFailover: false
    enableFreeTier: false
    enableMultipleWriteLocations: false
    isVirtualNetworkFilterEnabled: false
    networkAclBypass: 'None'
    publicNetworkAccess: 'Disabled'
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2026-03-15' = {
  parent: cosmos
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
    options: {
      autoscaleSettings: {
        maxThroughput: cosmosMaxThroughput
      }
    }
  }
}

var cosmosContainers = [
  {
    name: 'requests'
    partitionKey: '/requestId'
    defaultTtl: -1
  }
  {
    name: 'templates'
    partitionKey: '/templateId'
    defaultTtl: -1
  }
  {
    name: 'deliveries'
    partitionKey: '/requestId'
    defaultTtl: -1
  }
  {
    name: 'evaluations'
    partitionKey: '/datasetId'
    defaultTtl: -1
  }
  {
    name: 'idempotency'
    partitionKey: '/scopeId'
    defaultTtl: 2592000
  }
]

resource sqlContainers 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2026-03-15' = [
  for container in cosmosContainers: {
    parent: database
    name: container.name
    properties: {
      resource: {
        id: container.name
        defaultTtl: container.defaultTtl
        partitionKey: {
          paths: [
            container.partitionKey
          ]
          kind: 'Hash'
          version: 2
        }
        indexingPolicy: {
          automatic: true
          indexingMode: 'consistent'
          includedPaths: [
            {
              path: '/*'
            }
          ]
          excludedPaths: [
            {
              path: '/"_etag"/?'
            }
          ]
        }
      }
      options: {}
    }
  }
]

resource search 'Microsoft.Search/searchServices@2025-05-01' = {
  name: searchName
  location: location
  tags: tags
  sku: {
    name: 'standard'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    authOptions: {
      aadOrApiKey: {
        aadAuthFailureMode: 'http401WithBearerChallenge'
      }
    }
    disableLocalAuth: true
    encryptionWithCmk: {
      enforcement: 'Unspecified'
    }
    hostingMode: 'Default'
    networkRuleSet: {
      bypass: 'None'
      ipRules: []
    }
    partitionCount: 1
    publicNetworkAccess: 'disabled'
    replicaCount: zoneRedundant ? 2 : 1
    semanticSearch: 'free'
  }
}

resource serviceBus 'Microsoft.ServiceBus/namespaces@2026-01-01' = {
  name: serviceBusName
  location: location
  tags: tags
  sku: {
    name: 'Premium'
    tier: 'Premium'
    capacity: 1
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    disableLocalAuth: true
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Disabled'
    zoneRedundant: zoneRedundant
  }
}

resource domainEvents 'Microsoft.ServiceBus/namespaces/topics@2026-01-01' = {
  parent: serviceBus
  name: topicName
  properties: {
    defaultMessageTimeToLive: 'P14D'
    duplicateDetectionHistoryTimeWindow: 'PT10M'
    enableBatchedOperations: true
    enableExpress: false
    enablePartitioning: false
    maxMessageSizeInKilobytes: 1024
    maxSizeInMegabytes: 1024
    requiresDuplicateDetection: true
    status: 'Active'
    supportOrdering: true
  }
}

var subscriptionDefinitions = [
  {
    name: 'notifications'
    maxDeliveryCount: 10
  }
  {
    name: 'integrations'
    maxDeliveryCount: 10
  }
  {
    name: 'completion'
    maxDeliveryCount: 10
  }
  {
    name: 'retention'
    maxDeliveryCount: 5
  }
]

resource subscriptions 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2026-01-01' = [
  for subscriptionDefinition in subscriptionDefinitions: {
    parent: domainEvents
    name: subscriptionDefinition.name
    properties: {
      deadLetteringOnFilterEvaluationExceptions: true
      deadLetteringOnMessageExpiration: true
      defaultMessageTimeToLive: 'P14D'
      enableBatchedOperations: true
      lockDuration: 'PT1M'
      maxDeliveryCount: subscriptionDefinition.maxDeliveryCount
      status: 'Active'
    }
  }
]

resource keyVault 'Microsoft.KeyVault/vaults@2026-02-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    tenantId: tenant().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    accessPolicies: []
    enablePurgeProtection: true
    enableRbacAuthorization: true
    enableSoftDelete: true
    publicNetworkAccess: 'Disabled'
    softDeleteRetentionInDays: 90
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
      ipRules: []
      virtualNetworkRules: []
    }
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2025-04-01' = {
  name: registryName
  location: location
  tags: tags
  sku: {
    name: 'Premium'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    adminUserEnabled: false
    anonymousPullEnabled: false
    dataEndpointEnabled: true
    networkRuleBypassOptions: 'AzureServices'
    publicNetworkAccess: 'Disabled'
    zoneRedundancy: zoneRedundant ? 'Enabled' : 'Disabled'
    policies: {
      exportPolicy: {
        status: 'disabled'
      }
      quarantinePolicy: {
        status: 'disabled'
      }
      retentionPolicy: {
        days: 30
        status: 'enabled'
      }
      trustPolicy: {
        status: 'disabled'
        type: 'Notary'
      }
    }
  }
}

resource storageDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'send-to-log-analytics'
  scope: storage
  properties: {
    workspaceId: workspaceId
    metrics: [
      {
        category: 'Transaction'
        enabled: true
      }
    ]
  }
}

resource foundryStorageDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'send-to-log-analytics'
  scope: foundryStorage
  properties: {
    workspaceId: workspaceId
    metrics: [
      {
        category: 'Transaction'
        enabled: true
      }
    ]
  }
}

resource cosmosDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'send-to-log-analytics'
  scope: cosmos
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
        category: 'Requests'
        enabled: true
      }
    ]
  }
}

resource foundryCosmosDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'send-to-log-analytics'
  scope: foundryCosmos
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
        category: 'Requests'
        enabled: true
      }
    ]
  }
}

resource searchDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'send-to-log-analytics'
  scope: search
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

resource serviceBusDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'send-to-log-analytics'
  scope: serviceBus
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

resource keyVaultDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'send-to-log-analytics'
  scope: keyVault
  properties: {
    workspaceId: workspaceId
    logs: [
      {
        categoryGroup: 'audit'
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

resource registryDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'send-to-log-analytics'
  scope: registry
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

output storage object = {
  id: storage.id
  name: storage.name
  blobEndpoint: storage.properties.primaryEndpoints.blob
}
output foundryStorage object = {
  id: foundryStorage.id
  name: foundryStorage.name
  blobEndpoint: foundryStorage.properties.primaryEndpoints.blob
}
output cosmos object = {
  id: cosmos.id
  name: cosmos.name
  endpoint: cosmos.properties.documentEndpoint
  databaseName: database.name
}
output foundryCosmos object = {
  id: foundryCosmos.id
  name: foundryCosmos.name
  endpoint: foundryCosmos.properties.documentEndpoint
}
output search object = {
  id: search.id
  name: search.name
  endpoint: 'https://${search.name}.search.windows.net'
}
output serviceBus object = {
  id: serviceBus.id
  name: serviceBus.name
  endpoint: 'sb://${serviceBus.name}.servicebus.windows.net/'
  topicName: domainEvents.name
}
output keyVault object = {
  id: keyVault.id
  name: keyVault.name
  uri: keyVault.properties.vaultUri
}
output registry object = {
  id: registry.id
  name: registry.name
  loginServer: registry.properties.loginServer
}
