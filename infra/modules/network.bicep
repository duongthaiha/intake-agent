// Network module — VNet, subnets, private DNS zones, optional private endpoints
// Private endpoints are toggled by deployPrivateEndpoints parameter.
// Connectivity spike must pass before setting deployPrivateEndpoints=true in production.
targetScope = 'resourceGroup'

param location string
param tags object
param vnetName string
param deployPrivateEndpoints bool
@description('Deploy only the storage blob private endpoint (enables in-VNet FC1 deployment without enabling all PEs).')
param deployStoragePrivateEndpoint bool = false

// Resource names of data services (used for private endpoint creation)
param cosmosAccountName string
param storageAccountName string
param searchServiceName string
param keyVaultName string

// ---------------------------------------------------------------------------
// VNet
// ---------------------------------------------------------------------------

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: vnetName
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: ['10.0.0.0/16']
    }
    subnets: [
      {
        name: 'snet-private-endpoints'
        properties: {
          addressPrefix: '10.0.1.0/24'
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
      {
        name: 'snet-functions'
        properties: {
          addressPrefix: '10.0.2.0/24'
          privateEndpointNetworkPolicies: 'Enabled'
          serviceEndpoints: [
            {
              service: 'Microsoft.Storage'
              locations: [location]
            }
          ]
          delegations: [
            {
              // Flex Consumption (FC1) runs on Container Apps Legion infrastructure.
              // It requires Microsoft.App/environments delegation, not Microsoft.Web/serverFarms.
              name: 'Microsoft.App.environments'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
      {
        name: 'snet-foundry-agent'
        properties: {
          addressPrefix: '10.0.3.0/24'
          privateEndpointNetworkPolicies: 'Enabled'
          delegations: [
            {
              name: 'Microsoft.App.environments'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
      {
        name: 'snet-container-apps'
        properties: {
          addressPrefix: '10.0.4.0/23'
          privateEndpointNetworkPolicies: 'Enabled'
          delegations: [
            {
              name: 'Microsoft.App.environments'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
    ]
  }
}

// Convenience references to subnets
var peSubnetId = '${vnet.id}/subnets/snet-private-endpoints'
var functionsSubnetId = '${vnet.id}/subnets/snet-functions'
var foundryAgentSubnetId = '${vnet.id}/subnets/snet-foundry-agent'
var containerAppsSubnetId = '${vnet.id}/subnets/snet-container-apps'

// ---------------------------------------------------------------------------
// Private DNS zones (always created; linked to VNet only when PE enabled)
// ---------------------------------------------------------------------------

var dnsZones = [
  'privatelink.documents.azure.com'
  'privatelink.blob.${environment().suffixes.storage}'
  'privatelink.servicebus.windows.net'
  'privatelink.search.windows.net'
  'privatelink.vaultcore.azure.net'
  'privatelink.services.ai.azure.com'
  'privatelink.openai.azure.com'
  'privatelink.cognitiveservices.azure.com'
]

resource privateDnsZones 'Microsoft.Network/privateDnsZones@2020-06-01' = [for zone in dnsZones: {
  name: zone
  location: 'global'
  tags: tags
}]

resource dnsZoneLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = [for (zone, i) in dnsZones: {
  parent: privateDnsZones[i]
  name: 'link-${vnetName}'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}]

// ---------------------------------------------------------------------------
// Existing resource references for private endpoints
// ---------------------------------------------------------------------------

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' existing = if (deployPrivateEndpoints) {
  name: cosmosAccountName
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = if (deployPrivateEndpoints || deployStoragePrivateEndpoint) {
  name: storageAccountName
}

resource searchService 'Microsoft.Search/searchServices@2023-11-01' existing = if (deployPrivateEndpoints) {
  name: searchServiceName
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = if (deployPrivateEndpoints) {
  name: keyVaultName
}

// ---------------------------------------------------------------------------
// Private endpoints — created only when deployPrivateEndpoints == true
// ---------------------------------------------------------------------------

resource cosmosPrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-11-01' = if (deployPrivateEndpoints) {
  name: 'pe-${cosmosAccountName}-sql'
  location: location
  tags: tags
  properties: {
    subnet: { id: peSubnetId }
    privateLinkServiceConnections: [
      {
        name: 'pl-${cosmosAccountName}-sql'
        properties: {
          privateLinkServiceId: cosmosAccount.id
          groupIds: ['Sql']
        }
      }
    ]
  }
}

resource cosmosPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = if (deployPrivateEndpoints) {
  parent: cosmosPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink-documents'
        properties: {
          privateDnsZoneId: privateDnsZones[0].id
        }
      }
    ]
  }
}

resource storagePrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-11-01' = if (deployPrivateEndpoints || deployStoragePrivateEndpoint) {
  name: 'pe-${storageAccountName}-blob'
  location: location
  tags: tags
  properties: {
    subnet: { id: peSubnetId }
    privateLinkServiceConnections: [
      {
        name: 'pl-${storageAccountName}-blob'
        properties: {
          privateLinkServiceId: storageAccount.id
          groupIds: ['blob']
        }
      }
    ]
  }
}

resource storagePrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = if (deployPrivateEndpoints || deployStoragePrivateEndpoint) {
  parent: storagePrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink-blob'
        properties: {
          privateDnsZoneId: privateDnsZones[1].id
        }
      }
    ]
  }
}

resource searchPrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-11-01' = if (deployPrivateEndpoints) {
  name: 'pe-${searchServiceName}-searchService'
  location: location
  tags: tags
  properties: {
    subnet: { id: peSubnetId }
    privateLinkServiceConnections: [
      {
        name: 'pl-${searchServiceName}-searchService'
        properties: {
          privateLinkServiceId: searchService.id
          groupIds: ['searchService']
        }
      }
    ]
  }
}

resource searchPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = if (deployPrivateEndpoints) {
  parent: searchPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink-search'
        properties: {
          privateDnsZoneId: privateDnsZones[3].id
        }
      }
    ]
  }
}

resource kvPrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-11-01' = if (deployPrivateEndpoints) {
  name: 'pe-${keyVaultName}-vault'
  location: location
  tags: tags
  properties: {
    subnet: { id: peSubnetId }
    privateLinkServiceConnections: [
      {
        name: 'pl-${keyVaultName}-vault'
        properties: {
          privateLinkServiceId: keyVault.id
          groupIds: ['vault']
        }
      }
    ]
  }
}

resource kvPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = if (deployPrivateEndpoints) {
  parent: kvPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink-vaultcore'
        properties: {
          privateDnsZoneId: privateDnsZones[4].id
        }
      }
    ]
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

output vnetId string = vnet.id
output vnetName string = vnet.name
output peSubnetId string = peSubnetId
output functionsSubnetId string = functionsSubnetId
output foundryAgentSubnetId string = foundryAgentSubnetId
output containerAppsSubnetId string = containerAppsSubnetId
output cosmosPrivateDnsZoneId string = privateDnsZones[0].id
output storageBlobPrivateDnsZoneId string = privateDnsZones[1].id
output serviceBusPrivateDnsZoneId string = privateDnsZones[2].id
output searchPrivateDnsZoneId string = privateDnsZones[3].id
output keyVaultPrivateDnsZoneId string = privateDnsZones[4].id
output foundryServicesPrivateDnsZoneId string = privateDnsZones[5].id
output foundryOpenAiPrivateDnsZoneId string = privateDnsZones[6].id
output foundryCognitiveServicesPrivateDnsZoneId string = privateDnsZones[7].id
