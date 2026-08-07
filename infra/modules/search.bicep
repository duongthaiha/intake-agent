// AI Search module — Basic tier for POC enterprise knowledge index
targetScope = 'resourceGroup'

param location string
param tags object
param searchServiceName string
param deployPrivateEndpoints bool
param agentIdentityPrincipalId string

// ---------------------------------------------------------------------------
// AI Search service
// ---------------------------------------------------------------------------

resource searchService 'Microsoft.Search/searchServices@2023-11-01' = {
  name: searchServiceName
  location: location
  tags: tags
  sku: {
    name: 'standard'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    publicNetworkAccess: deployPrivateEndpoints ? 'disabled' : 'enabled'
    networkRuleSet: deployPrivateEndpoints ? {
      ipRules: []
      bypass: 'None'
    } : {
      ipRules: []
      bypass: 'AzurePortal'
    }
    encryptionWithCmk: {
      enforcement: 'Unspecified'
    }
    disableLocalAuth: false
    authOptions: {
      aadOrApiKey: {
        aadAuthFailureMode: 'http403'
      }
    }
    semanticSearch: 'disabled'
  }
}

// ---------------------------------------------------------------------------
// RBAC
// ---------------------------------------------------------------------------

var searchIndexDataReaderRoleId = '1407120a-92aa-4202-b7e9-c0e197c71c8f'

resource agentSearchReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(searchService.id, agentIdentityPrincipalId, searchIndexDataReaderRoleId)
  scope: searchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataReaderRoleId)
    principalId: agentIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Search service system identity needs Storage Blob Data Reader to index blob storage
// (assigned when document indexer is configured — left as a note for Trinity)

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

output serviceId string = searchService.id
output serviceName string = searchService.name
output endpoint string = 'https://${searchService.name}.search.windows.net'
