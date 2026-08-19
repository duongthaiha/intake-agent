// Storage module — blob storage for artifacts and Functions deployment packages
targetScope = 'resourceGroup'

param location string
param tags object
param storageAccountName string
param workerIdentityPrincipalId string
param evalIdentityPrincipalId string
param functionsMIPrincipalId string
param mcpIdentityPrincipalId string
@description('VNet subnet ID for Functions service endpoint (allows Flex Consumption Legion to access storage when publicNetworkAccess=Disabled).')
param functionsSubnetId string = ''

// ---------------------------------------------------------------------------
// Storage account
// ---------------------------------------------------------------------------

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices, Logging, Metrics'
      virtualNetworkRules: !empty(functionsSubnetId) ? [{ id: functionsSubnetId, action: 'Allow' }] : []
    }
    encryption: {
      services: {
        blob: { enabled: true }
        file: { enabled: true }
      }
      keySource: 'Microsoft.Storage'
    }
  }
}

// ---------------------------------------------------------------------------
// Blob service
// ---------------------------------------------------------------------------

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 7
    }
  }
}

// ---------------------------------------------------------------------------
// Containers
// ---------------------------------------------------------------------------

resource artifactsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'request-artifacts'
  properties: {
    publicAccess: 'None'
  }
}

resource evalContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'eval-datasets'
  properties: {
    publicAccess: 'None'
  }
}

resource deploymentContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'deploymentpackage'
  properties: {
    publicAccess: 'None'
  }
}

// ---------------------------------------------------------------------------
// RBAC
// ---------------------------------------------------------------------------

var blobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var blobDataReaderRoleId = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'

resource workerBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, workerIdentityPrincipalId, blobDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributorRoleId)
    principalId: workerIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource evalBlobReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, evalIdentityPrincipalId, blobDataReaderRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataReaderRoleId)
    principalId: evalIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource functionsBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (functionsMIPrincipalId != workerIdentityPrincipalId) {
  name: guid(storageAccount.id, functionsMIPrincipalId, blobDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributorRoleId)
    principalId: functionsMIPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource mcpBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, mcpIdentityPrincipalId, blobDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributorRoleId)
    principalId: mcpIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Deployer identity RBAC (Storage Blob Data Contributor) is provisioned once via az role assignment create
// and persists across redeployments. It is NOT managed here to avoid ARM RoleAssignmentExists conflicts
// when the same deterministic GUID already exists in Azure from a previous provision.
// The assignment (GUID 4d2906ab...) is confirmed present and correct.

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

output accountId string = storageAccount.id
output accountName string = storageAccount.name
output blobEndpoint string = storageAccount.properties.primaryEndpoints.blob
output artifactsContainer string = artifactsContainer.name
output evalContainer string = evalContainer.name
output deploymentContainer string = deploymentContainer.name
