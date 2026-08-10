// Inbound private endpoint for a fully provisioned Microsoft Foundry account.
// Kept in a separate nested deployment because account creation is asynchronous.
targetScope = 'resourceGroup'

param location string
param tags object
param accountName string
param accountId string
param privateEndpointSubnetId string
param foundryPrivateDnsZoneIds array

resource foundryPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-${accountName}-account'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'pl-${accountName}-account'
        properties: {
          privateLinkServiceId: accountId
          groupIds: [
            'account'
          ]
        }
      }
    ]
  }
}

resource foundryPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: foundryPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      for (zoneId, index) in foundryPrivateDnsZoneIds: {
        name: 'foundry-${index}'
        properties: {
          privateDnsZoneId: zoneId
        }
      }
    ]
  }
}

output privateEndpointId string = foundryPrivateEndpoint.id
