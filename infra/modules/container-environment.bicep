@description('Azure region for the Container Apps environment.')
param location string

@description('Short, globally consistent resource-name suffix.')
param suffix string

@description('Common resource tags.')
param tags object

@description('Dedicated subnet resource ID for this managed environment.')
param infrastructureSubnetId string

@description('Log Analytics workspace customer ID.')
param workspaceCustomerId string

@secure()
@description('Log Analytics shared key. It is used only by the managed environment control plane.')
param workspaceSharedKey string

@description('Log Analytics workspace resource ID for diagnostic settings.')
param workspaceId string

@description('Enable zone redundancy where the selected region supports it.')
param zoneRedundant bool = false

var environmentName = 'cae-intake-${suffix}'

resource environment 'Microsoft.App/managedEnvironments@2026-01-01' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: workspaceCustomerId
        sharedKey: workspaceSharedKey
      }
    }
    infrastructureResourceGroup: 'ME_${environmentName}_${resourceGroup().name}_${location}'
    peerAuthentication: {
      mtls: {
        enabled: true
      }
    }
    peerTrafficConfiguration: {
      encryption: {
        enabled: true
      }
    }
    publicNetworkAccess: 'Disabled'
    vnetConfiguration: {
      infrastructureSubnetId: infrastructureSubnetId
      internal: true
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    zoneRedundant: zoneRedundant
  }
}

resource environmentDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'send-to-log-analytics'
  scope: environment
  properties: {
    workspaceId: workspaceId
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

output environment object = {
  id: environment.id
  name: environment.name
  defaultDomain: environment.properties.defaultDomain
  staticIp: environment.properties.staticIp
}
