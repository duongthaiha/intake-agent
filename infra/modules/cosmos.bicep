// Cosmos DB module — NoSQL account, database, and containers
// Serverless capacity mode for POC cost optimisation.
targetScope = 'resourceGroup'

param location string
param tags object
param accountName string
param deployPrivateEndpoints bool
param agentIdentityPrincipalId string
param workerIdentityPrincipalId string

// ---------------------------------------------------------------------------
// Cosmos DB account
// ---------------------------------------------------------------------------

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: accountName
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
        isZoneRedundant: false
      }
    ]
    capabilities: [
      { name: 'EnableServerless' }
    ]
    enableAnalyticalStorage: false
    publicNetworkAccess: deployPrivateEndpoints ? 'Disabled' : 'Enabled'
    networkAclBypass: 'AzureServices'
    networkAclBypassResourceIds: []
    backupPolicy: {
      type: 'Continuous'
      continuousModeProperties: {
        tier: 'Continuous7Days'
      }
    }
    minimalTlsVersion: 'Tls12'
    disableKeyBasedMetadataWriteAccess: false
  }
}

// ---------------------------------------------------------------------------
// Database
// ---------------------------------------------------------------------------

resource intakeDatabase 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmosAccount
  name: 'intake'
  properties: {
    resource: {
      id: 'intake'
    }
  }
}

// ---------------------------------------------------------------------------
// Containers
// ---------------------------------------------------------------------------

resource requestsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: intakeDatabase
  name: 'requests'
  properties: {
    resource: {
      id: 'requests'
      partitionKey: {
        paths: ['/tenantId']
        kind: 'Hash'
        version: 2
      }
      defaultTtl: -1
      indexingPolicy: {
        indexingMode: 'consistent'
        includedPaths: [{ path: '/*' }]
        excludedPaths: [{ path: '/"_etag"/?' }]
      }
    }
  }
}

resource revisionsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: intakeDatabase
  name: 'revisions'
  properties: {
    resource: {
      id: 'revisions'
      partitionKey: {
        paths: ['/requestId']
        kind: 'Hash'
        version: 2
      }
      defaultTtl: -1
      indexingPolicy: {
        indexingMode: 'consistent'
        includedPaths: [{ path: '/*' }]
        excludedPaths: [{ path: '/"_etag"/?' }]
      }
    }
  }
}

resource workflowEventsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: intakeDatabase
  name: 'workflow-events'
  properties: {
    resource: {
      id: 'workflow-events'
      partitionKey: {
        paths: ['/requestId']
        kind: 'Hash'
        version: 2
      }
      defaultTtl: -1
      indexingPolicy: {
        indexingMode: 'consistent'
        includedPaths: [{ path: '/*' }]
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Cosmos DB data-plane RBAC
// Built-in role IDs are fixed GUIDs scoped to the account, not Azure RBAC.
// ---------------------------------------------------------------------------

var cosmosDataContributorRoleDefId = '${cosmosAccount.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'

resource agentCosmosRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmosAccount
  name: guid(cosmosAccount.id, agentIdentityPrincipalId, '00000000-0000-0000-0000-000000000002')
  properties: {
    roleDefinitionId: cosmosDataContributorRoleDefId
    principalId: agentIdentityPrincipalId
    scope: cosmosAccount.id
  }
}

resource workerCosmosRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmosAccount
  name: guid(cosmosAccount.id, workerIdentityPrincipalId, '00000000-0000-0000-0000-000000000002')
  properties: {
    roleDefinitionId: cosmosDataContributorRoleDefId
    principalId: workerIdentityPrincipalId
    scope: cosmosAccount.id
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

output accountId string = cosmosAccount.id
output accountName string = cosmosAccount.name
output endpoint string = cosmosAccount.properties.documentEndpoint
output databaseName string = intakeDatabase.name
