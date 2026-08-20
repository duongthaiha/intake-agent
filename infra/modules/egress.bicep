@description('Azure region for controlled egress resources.')
param location string

@description('Short, globally consistent resource-name suffix.')
param suffix string

@description('Common resource tags.')
param tags object

@description('Dedicated AzureFirewallSubnet resource ID.')
param firewallSubnetId string

@description('Pre-created workload route table name.')
param routeTableName string

@description('Source address range permitted to use the firewall.')
param sourceAddressPrefix string = '10.42.0.0/16'

@description('Approved HTTPS destinations for agent and workload egress.')
param allowedFqdns array = [
  'graph.microsoft.com'
  replace(replace(environment().authentication.loginEndpoint, 'https://', ''), '/', '')
  replace(replace(environment().resourceManager, 'https://', ''), '/', '')
  'mcr.microsoft.com'
  '*.data.mcr.microsoft.com'
  'packages.aks.azure.com'
  'acs-mirror.azureedge.net'
  '*.azurecr.io'
  '*.data.azurecr.io'
  '*.identity.azure.net'
  '*.applicationinsights.azure.com'
  '*.monitor.azure.com'
  '*.services.ai.azure.com'
  '*.cognitiveservices.azure.com'
  '*.openai.azure.com'
  '*.servicebus.windows.net'
  '*.blob.${environment().suffixes.storage}'
  '*.documents.azure.com'
  '*.search.windows.net'
  '*.${environment().suffixes.keyvaultDns}'
  '*.teams.microsoft.com'
]

resource firewallPublicIp 'Microsoft.Network/publicIPAddresses@2024-07-01' = {
  name: 'pip-intake-firewall-${suffix}'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
    tier: 'Regional'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }
}

resource firewallPolicy 'Microsoft.Network/firewallPolicies@2024-07-01' = {
  name: 'afwp-intake-${suffix}'
  location: location
  tags: tags
  properties: {
    dnsSettings: {
      enableProxy: true
    }
    sku: {
      tier: 'Standard'
    }
    threatIntelMode: 'Deny'
  }
}

resource firewallRules 'Microsoft.Network/firewallPolicies/ruleCollectionGroups@2024-07-01' = {
  parent: firewallPolicy
  name: 'default'
  properties: {
    priority: 200
    ruleCollections: [
      {
        name: 'approved-https-egress'
        priority: 100
        ruleCollectionType: 'FirewallPolicyFilterRuleCollection'
        action: {
          type: 'Allow'
        }
        rules: [
          {
            name: 'approved-fqdns'
            ruleType: 'ApplicationRule'
            sourceAddresses: [
              sourceAddressPrefix
            ]
            protocols: [
              {
                protocolType: 'Https'
                port: 443
              }
            ]
            targetFqdns: allowedFqdns
            terminateTLS: false
          }
        ]
      }
    ]
  }
}

resource firewall 'Microsoft.Network/azureFirewalls@2024-07-01' = {
  name: 'afw-intake-${suffix}'
  location: location
  tags: tags
  properties: {
    firewallPolicy: {
      id: firewallPolicy.id
    }
    ipConfigurations: [
      {
        name: 'default'
        properties: {
          publicIPAddress: {
            id: firewallPublicIp.id
          }
          subnet: {
            id: firewallSubnetId
          }
        }
      }
    ]
    sku: {
      name: 'AZFW_VNet'
      tier: 'Standard'
    }
    threatIntelMode: 'Deny'
  }
  dependsOn: [
    firewallRules
  ]
}

resource workloadRouteTable 'Microsoft.Network/routeTables@2024-07-01' existing = {
  name: routeTableName
}

resource defaultRoute 'Microsoft.Network/routeTables/routes@2024-07-01' = {
  parent: workloadRouteTable
  name: 'default-via-firewall'
  properties: {
    addressPrefix: '0.0.0.0/0'
    nextHopType: 'VirtualAppliance'
    nextHopIpAddress: firewall.properties.ipConfigurations[0].properties.privateIPAddress
  }
}

output routeTableId string = workloadRouteTable.id
output firewallId string = firewall.id
output firewallPrivateIp string = firewall.properties.ipConfigurations[0].properties.privateIPAddress
