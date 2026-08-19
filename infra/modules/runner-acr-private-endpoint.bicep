// Inbound private endpoint for the runner ACR.
// Kept as a separate module (output-referencing runner-acr.bicep) rather
// than folded into network.bicep so ARM's implicit dependency graph orders
// this strictly after ACR creation — avoiding the "existing resource
// referenced before it exists" ordering trap that a same-module reference
// pattern would hit on a from-scratch deployment.
targetScope = 'resourceGroup'

param location string
param tags object
param acrName string
param acrId string
param privateEndpointSubnetId string
param acrPrivateDnsZoneId string

resource acrPrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-11-01' = {
  name: 'pe-${acrName}-registry'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'pl-${acrName}-registry'
        properties: {
          privateLinkServiceId: acrId
          groupIds: [
            'registry'
          ]
        }
      }
    ]
  }
}

resource acrPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = {
  parent: acrPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink-azurecr'
        properties: {
          privateDnsZoneId: acrPrivateDnsZoneId
        }
      }
    ]
  }
}

output privateEndpointId string = acrPrivateEndpoint.id
