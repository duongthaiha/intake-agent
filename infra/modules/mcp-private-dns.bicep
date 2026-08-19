// DNS for an internal Container Apps environment.
targetScope = 'resourceGroup'

param tags object
param defaultDomain string
param staticIp string
param vnetId string
param linkName string

resource mcpDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: defaultDomain
  location: 'global'
  tags: tags
}

resource wildcardRecord 'Microsoft.Network/privateDnsZones/A@2020-06-01' = {
  parent: mcpDnsZone
  name: '*'
  properties: {
    ttl: 300
    aRecords: [
      {
        ipv4Address: staticIp
      }
    ]
  }
}

resource vnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: mcpDnsZone
  name: linkName
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnetId
    }
  }
}

output zoneId string = mcpDnsZone.id
