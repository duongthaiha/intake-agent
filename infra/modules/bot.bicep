// Bot Service module — Azure Bot Service for Teams channel publishing
//
// ⚠️  GATED — deployBotService must be true in main.bicep parameters.
// ⚠️  REQUIRES Microsoft.BotService provider registration.
// ⚠️  REQUIRES Teams publishing spike findings (see .azure/deployment-plan.md §5.1).
//
// The bot endpoint must be updated post-deploy to point to the Foundry activity protocol URL:
//   https://<ais-resource>.services.ai.azure.com/api/projects/<project>/agents/<agent>/endpoint/protocols/activityProtocol?api-version=2025-05-15-preview
//
// Spike questions still open:
//   - F0 (free) vs S1 tier support for Activity Protocol traffic
//   - M365 admin consent requirements for tenant-scoped publishing
targetScope = 'resourceGroup'

param tags object
param botServiceName string
@description('Bot endpoint — Foundry activity protocol URL. Update after agent is deployed.')
param botEndpoint string = 'https://placeholder.services.ai.azure.com'
@description('Microsoft App ID (Entra app registration). Create manually and provide here.')
param msaAppId string = ''
@description('Bot Service SKU. F0 = free (validate capacity); S1 = standard (~$50/month).')
@allowed(['F0', 'S1'])
param botSku string = 'S1'

// ---------------------------------------------------------------------------
// Bot Service
// ---------------------------------------------------------------------------

resource botService 'Microsoft.BotService/botServices@2022-09-15' = {
  name: botServiceName
  location: 'global'  // Bot Service is a global resource
  tags: tags
  kind: 'azurebot'
  sku: {
    name: botSku
  }
  properties: {
    displayName: 'Intake Agent'
    description: 'Intake Agent — structured requirements capture via Teams'
    endpoint: botEndpoint
    msaAppId: !empty(msaAppId) ? msaAppId : ''
    msaAppType: 'UserAssignedMSI'
    publicNetworkAccess: 'Enabled'
    isStreamingSupported: false
  }
}

// Teams channel
resource teamsChannel 'Microsoft.BotService/botServices/channels@2022-09-15' = {
  parent: botService
  name: 'MsTeamsChannel'
  location: 'global'
  properties: {
    channelName: 'MsTeamsChannel'
    properties: {
      enableCalling: false
      isEnabled: true
    }
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

output botServiceId string = botService.id
output botServiceName string = botService.name
