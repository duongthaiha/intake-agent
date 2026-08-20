@description('Dedicated application virtual network name.')
param virtualNetworkName string

@description('Hardened workload route table resource ID.')
param routeTableId string

@description('Foundry subnet NSG resource ID.')
param foundryNetworkSecurityGroupId string

@description('Container Apps subnet NSG resource ID.')
param containerAppsNetworkSecurityGroupId string

@description('Functions subnet NSG resource ID.')
param functionsNetworkSecurityGroupId string

resource virtualNetwork 'Microsoft.Network/virtualNetworks@2025-01-01' existing = {
  name: virtualNetworkName
}

resource foundrySubnet 'Microsoft.Network/virtualNetworks/subnets@2025-01-01' = {
  parent: virtualNetwork
  name: 'snet-foundry-agents'
  properties: {
    addressPrefix: '10.42.0.0/24'
    networkSecurityGroup: {
      id: foundryNetworkSecurityGroupId
    }
    routeTable: {
      id: routeTableId
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

resource containerAppsSubnet 'Microsoft.Network/virtualNetworks/subnets@2025-01-01' = {
  parent: virtualNetwork
  name: 'snet-container-apps'
  properties: {
    addressPrefix: '10.42.2.0/23'
    networkSecurityGroup: {
      id: containerAppsNetworkSecurityGroupId
    }
    routeTable: {
      id: routeTableId
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

resource functionsSubnet 'Microsoft.Network/virtualNetworks/subnets@2025-01-01' = {
  parent: virtualNetwork
  name: 'snet-functions-integration'
  properties: {
    addressPrefix: '10.42.4.0/24'
    networkSecurityGroup: {
      id: functionsNetworkSecurityGroupId
    }
    routeTable: {
      id: routeTableId
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
