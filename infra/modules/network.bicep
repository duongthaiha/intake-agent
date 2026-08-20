@description('Azure region for network resources.')
param location string

@description('Short, globally consistent resource-name suffix.')
param suffix string

@description('Common resource tags.')
param tags object

@description('Address space for the dedicated application virtual network.')
param virtualNetworkAddressPrefix string = '10.42.0.0/16'

@description('Dedicated /24 subnet used only for Microsoft Foundry agent network injection.')
param foundrySubnetPrefix string = '10.42.0.0/24'

@description('Dedicated subnet used only by the workload-profile Container Apps managed environment.')
param containerAppsSubnetPrefix string = '10.42.2.0/23'

@description('Subnet reserved for conventional Azure Functions regional VNet integration if adopted.')
param functionsSubnetPrefix string = '10.42.4.0/24'

@description('Dedicated subnet for private endpoints.')
param privateEndpointSubnetPrefix string = '10.42.5.0/24'

@description('Dedicated Azure Firewall subnet used by hardened deployments.')
param firewallSubnetPrefix string = '10.42.6.0/26'

var vnetName = 'vnet-intake-${suffix}'

resource foundryNsg 'Microsoft.Network/networkSecurityGroups@2025-01-01' = {
  name: 'nsg-intake-foundry-${suffix}'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'DenyInternetInbound'
        properties: {
          priority: 4000
          access: 'Deny'
          direction: 'Inbound'
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: 'Internet'
          destinationAddressPrefix: '*'
        }
      }
    ]
  }
}

resource containerAppsNsg 'Microsoft.Network/networkSecurityGroups@2025-01-01' = {
  name: 'nsg-intake-containerapps-${suffix}'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'DenyInternetInbound'
        properties: {
          priority: 4000
          access: 'Deny'
          direction: 'Inbound'
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: 'Internet'
          destinationAddressPrefix: '*'
        }
      }
    ]
  }
}

resource functionsNsg 'Microsoft.Network/networkSecurityGroups@2025-01-01' = {
  name: 'nsg-intake-functions-${suffix}'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'DenyInternetInbound'
        properties: {
          priority: 4000
          access: 'Deny'
          direction: 'Inbound'
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: 'Internet'
          destinationAddressPrefix: '*'
        }
      }
    ]
  }
}

resource privateEndpointNsg 'Microsoft.Network/networkSecurityGroups@2025-01-01' = {
  name: 'nsg-intake-private-endpoints-${suffix}'
  location: location
  tags: tags
}

resource virtualNetwork 'Microsoft.Network/virtualNetworks@2025-01-01' = {
  name: vnetName
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        virtualNetworkAddressPrefix
      ]
    }
    dhcpOptions: {
      dnsServers: []
    }
    subnets: [
      {
        name: 'snet-foundry-agents'
        properties: {
          addressPrefix: foundrySubnetPrefix
          networkSecurityGroup: {
            id: foundryNsg.id
          }
          delegations: [
            {
              name: 'foundry-agent-injection'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
          privateEndpointNetworkPolicies: 'Enabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
      {
        name: 'snet-container-apps'
        properties: {
          addressPrefix: containerAppsSubnetPrefix
          networkSecurityGroup: {
            id: containerAppsNsg.id
          }
          delegations: [
            {
              name: 'container-apps-environment'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
          privateEndpointNetworkPolicies: 'Enabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
      {
        name: 'snet-functions-integration'
        properties: {
          addressPrefix: functionsSubnetPrefix
          networkSecurityGroup: {
            id: functionsNsg.id
          }
          delegations: [
            {
              name: 'functions-integration'
              properties: {
                serviceName: 'Microsoft.Web/serverFarms'
              }
            }
          ]
          privateEndpointNetworkPolicies: 'Enabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
      {
        name: 'snet-private-endpoints'
        properties: {
          addressPrefix: privateEndpointSubnetPrefix
          networkSecurityGroup: {
            id: privateEndpointNsg.id
          }
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
      {
        name: 'AzureFirewallSubnet'
        properties: {
          addressPrefix: firewallSubnetPrefix
          privateEndpointNetworkPolicies: 'Enabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
    ]
  }
}

output virtualNetworkId string = virtualNetwork.id
output virtualNetworkName string = virtualNetwork.name
output foundrySubnetId string = resourceId('Microsoft.Network/virtualNetworks/subnets', virtualNetwork.name, 'snet-foundry-agents')
output containerAppsSubnetId string = resourceId('Microsoft.Network/virtualNetworks/subnets', virtualNetwork.name, 'snet-container-apps')
output functionsSubnetId string = resourceId('Microsoft.Network/virtualNetworks/subnets', virtualNetwork.name, 'snet-functions-integration')
output privateEndpointSubnetId string = resourceId('Microsoft.Network/virtualNetworks/subnets', virtualNetwork.name, 'snet-private-endpoints')
output firewallSubnetId string = resourceId('Microsoft.Network/virtualNetworks/subnets', virtualNetwork.name, 'AzureFirewallSubnet')
output foundryNetworkSecurityGroupId string = foundryNsg.id
output containerAppsNetworkSecurityGroupId string = containerAppsNsg.id
output functionsNetworkSecurityGroupId string = functionsNsg.id
