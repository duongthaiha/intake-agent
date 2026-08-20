@description('Azure region for observability resources.')
param location string

@description('Short, globally consistent resource-name suffix.')
param suffix string

@description('Common resource tags.')
param tags object

@description('When true, monitoring ingestion and query must traverse Azure Monitor Private Link.')
param hardened bool = true

@minValue(30)
@maxValue(730)
@description('Log Analytics retention in days.')
param retentionInDays int = 90

var workspaceName = 'log-intake-${suffix}'
var applicationInsightsName = 'appi-intake-${suffix}'
var privateLinkScopeName = 'ampls-intake-${suffix}'

resource workspace 'Microsoft.OperationalInsights/workspaces@2025-07-01' = {
  name: workspaceName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: retentionInDays
    publicNetworkAccessForIngestion: hardened ? 'Disabled' : 'Enabled'
    publicNetworkAccessForQuery: hardened ? 'Disabled' : 'Enabled'
    features: {
      disableLocalAuth: false
      enableLogAccessUsingOnlyResourcePermissions: true
    }
  }
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: applicationInsightsName
  location: location
  kind: 'web'
  tags: tags
  properties: {
    Application_Type: 'web'
    Flow_Type: 'Bluefield'
    IngestionMode: 'LogAnalytics'
    WorkspaceResourceId: workspace.id
    DisableLocalAuth: true
    publicNetworkAccessForIngestion: hardened ? 'Disabled' : 'Enabled'
    publicNetworkAccessForQuery: hardened ? 'Disabled' : 'Enabled'
    RetentionInDays: retentionInDays
  }
}

resource privateLinkScope 'Microsoft.Insights/privateLinkScopes@2021-09-01' = {
  name: privateLinkScopeName
  location: 'global'
  tags: tags
  properties: {
    accessModeSettings: {
      ingestionAccessMode: hardened ? 'PrivateOnly' : 'Open'
      queryAccessMode: hardened ? 'PrivateOnly' : 'Open'
      exclusions: []
    }
  }
}

resource workspaceScope 'Microsoft.Insights/privateLinkScopes/scopedResources@2021-09-01' = {
  parent: privateLinkScope
  name: 'workspace'
  properties: {
    linkedResourceId: workspace.id
  }
}

resource applicationInsightsScope 'Microsoft.Insights/privateLinkScopes/scopedResources@2021-09-01' = {
  parent: privateLinkScope
  name: 'application-insights'
  properties: {
    linkedResourceId: applicationInsights.id
  }
}

output workspaceId string = workspace.id
output workspaceName string = workspace.name
output workspaceCustomerId string = workspace.properties.customerId
@secure()
output workspaceSharedKey string = workspace.listKeys().primarySharedKey
output applicationInsightsId string = applicationInsights.id
output applicationInsightsName string = applicationInsights.name
output applicationInsightsConnectionString string = applicationInsights.properties.ConnectionString
output privateLinkScopeId string = privateLinkScope.id
output privateLinkScopeName string = privateLinkScope.name
