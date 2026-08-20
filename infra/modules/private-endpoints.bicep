@description('Azure region for private endpoints.')
param location string

@description('Short, globally consistent resource-name suffix.')
param suffix string

@description('Common resource tags.')
param tags object

@description('Dedicated private endpoint subnet resource ID.')
param privateEndpointSubnetId string

@description('Dedicated application virtual network resource ID.')
param virtualNetworkId string

@description('Persistent resource IDs used as Private Link targets.')
param targets object

var dnsZoneNames = [
  'privatelink.cognitiveservices.azure.com'
  'privatelink.openai.azure.com'
  'privatelink.services.ai.azure.com'
  'privatelink.search.windows.net'
  'privatelink.documents.azure.com'
  'privatelink.blob.${environment().suffixes.storage}'
  'privatelink.queue.${environment().suffixes.storage}'
  'privatelink.table.${environment().suffixes.storage}'
  'privatelink.file.${environment().suffixes.storage}'
  'privatelink.servicebus.windows.net'
  'privatelink.vaultcore.azure.net'
  'privatelink.azurecr.io'
  'privatelink.monitor.azure.com'
  'privatelink.oms.opinsights.azure.com'
  'privatelink.ods.opinsights.azure.com'
  'privatelink.agentsvc.azure-automation.net'
]

resource dnsZones 'Microsoft.Network/privateDnsZones@2024-06-01' = [
  for dnsZoneName in dnsZoneNames: {
    name: dnsZoneName
    location: 'global'
    tags: tags
  }
]

resource dnsLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [
  for (dnsZoneName, index) in dnsZoneNames: {
    parent: dnsZones[index]
    name: 'vnet-${suffix}'
    location: 'global'
    tags: tags
    properties: {
      registrationEnabled: false
      virtualNetwork: {
        id: virtualNetworkId
      }
    }
  }
]

var endpointDefinitions = [
  {
    name: 'pe-foundry-${suffix}'
    targetId: targets.foundry
    groupId: 'account'
    zones: [
      'privatelink.cognitiveservices.azure.com'
      'privatelink.openai.azure.com'
      'privatelink.services.ai.azure.com'
    ]
  }
  {
    name: 'pe-search-${suffix}'
    targetId: targets.search
    groupId: 'searchService'
    zones: [
      'privatelink.search.windows.net'
    ]
  }
  {
    name: 'pe-cosmos-${suffix}'
    targetId: targets.cosmos
    groupId: 'Sql'
    zones: [
      'privatelink.documents.azure.com'
    ]
  }
  {
    name: 'pe-foundry-cosmos-${suffix}'
    targetId: targets.foundryCosmos
    groupId: 'Sql'
    zones: [
      'privatelink.documents.azure.com'
    ]
  }
  {
    name: 'pe-storage-blob-${suffix}'
    targetId: targets.storage
    groupId: 'blob'
    zones: [
      'privatelink.blob.${environment().suffixes.storage}'
    ]
  }
  {
    name: 'pe-foundry-storage-blob-${suffix}'
    targetId: targets.foundryStorage
    groupId: 'blob'
    zones: [
      'privatelink.blob.${environment().suffixes.storage}'
    ]
  }
  {
    name: 'pe-storage-queue-${suffix}'
    targetId: targets.storage
    groupId: 'queue'
    zones: [
      'privatelink.queue.${environment().suffixes.storage}'
    ]
  }
  {
    name: 'pe-storage-table-${suffix}'
    targetId: targets.storage
    groupId: 'table'
    zones: [
      'privatelink.table.${environment().suffixes.storage}'
    ]
  }
  {
    name: 'pe-storage-file-${suffix}'
    targetId: targets.storage
    groupId: 'file'
    zones: [
      'privatelink.file.${environment().suffixes.storage}'
    ]
  }
  {
    name: 'pe-servicebus-${suffix}'
    targetId: targets.serviceBus
    groupId: 'namespace'
    zones: [
      'privatelink.servicebus.windows.net'
    ]
  }
  {
    name: 'pe-keyvault-${suffix}'
    targetId: targets.keyVault
    groupId: 'vault'
    zones: [
      'privatelink.vaultcore.azure.net'
    ]
  }
  {
    name: 'pe-registry-${suffix}'
    targetId: targets.registry
    groupId: 'registry'
    zones: [
      'privatelink.azurecr.io'
    ]
  }
  {
    name: 'pe-monitor-${suffix}'
    targetId: targets.monitorPrivateLinkScope
    groupId: 'azuremonitor'
    zones: [
      'privatelink.monitor.azure.com'
      'privatelink.oms.opinsights.azure.com'
      'privatelink.ods.opinsights.azure.com'
      'privatelink.agentsvc.azure-automation.net'
      'privatelink.blob.${environment().suffixes.storage}'
    ]
  }
]

resource privateEndpoints 'Microsoft.Network/privateEndpoints@2025-05-01' = [
  for endpoint in endpointDefinitions: {
    name: endpoint.name
    location: location
    tags: tags
    properties: {
      customNetworkInterfaceName: 'nic-${endpoint.name}'
      privateLinkServiceConnections: [
        {
          name: 'connection'
          properties: {
            groupIds: [
              endpoint.groupId
            ]
            privateLinkServiceId: endpoint.targetId
            requestMessage: 'Managed by Intake Agent infrastructure.'
          }
        }
      ]
      subnet: {
        id: privateEndpointSubnetId
      }
    }
  }
]

resource privateDnsZoneGroups 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2025-05-01' = [
  for (endpoint, index) in endpointDefinitions: {
    parent: privateEndpoints[index]
    name: 'default'
    properties: {
      privateDnsZoneConfigs: [
        for (zoneName, zoneIndex) in endpoint.zones: {
          name: 'zone-${zoneIndex}'
          properties: {
            privateDnsZoneId: resourceId('Microsoft.Network/privateDnsZones', zoneName)
          }
        }
      ]
    }
    dependsOn: [
      for dnsLink in dnsLinks: dnsLink
    ]
  }
]

output privateEndpointIds array = [
  for (endpoint, index) in endpointDefinitions: privateEndpoints[index].id
]
