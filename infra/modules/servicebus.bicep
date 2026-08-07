// Service Bus module — Standard namespace, queues for domain events and DLQ recovery
targetScope = 'resourceGroup'

param location string
param tags object
param namespaceName string
param deployPrivateEndpoints bool
param agentIdentityPrincipalId string
param workerIdentityPrincipalId string

// ---------------------------------------------------------------------------
// Service Bus namespace
// ---------------------------------------------------------------------------

resource sbNamespace 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' = {
  name: namespaceName
  location: location
  tags: tags
  sku: {
    name: 'Standard'
    tier: 'Standard'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    minimumTlsVersion: '1.2'
    disableLocalAuth: false
    publicNetworkAccess: deployPrivateEndpoints ? 'Disabled' : 'Enabled'
  }
}

// ---------------------------------------------------------------------------
// Queues
// ---------------------------------------------------------------------------

resource domainEventsQueue 'Microsoft.ServiceBus/namespaces/queues@2022-10-01-preview' = {
  parent: sbNamespace
  name: 'domain-events'
  properties: {
    maxDeliveryCount: 10
    lockDuration: 'PT5M'
    defaultMessageTimeToLive: 'P14D'
    deadLetteringOnMessageExpiration: true
    enablePartitioning: false
    requiresDuplicateDetection: false
    requiresSession: false
  }
}

resource dlqRecoveryQueue 'Microsoft.ServiceBus/namespaces/queues@2022-10-01-preview' = {
  parent: sbNamespace
  name: 'domain-events-dlq-recovery'
  properties: {
    maxDeliveryCount: 3
    lockDuration: 'PT5M'
    defaultMessageTimeToLive: 'P7D'
    enablePartitioning: false
    requiresDuplicateDetection: false
    requiresSession: false
  }
}

// ---------------------------------------------------------------------------
// RBAC
// ---------------------------------------------------------------------------

var sbDataSenderRoleId = '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39'
var sbDataReceiverRoleId = '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0'

resource agentSbSender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(sbNamespace.id, agentIdentityPrincipalId, sbDataSenderRoleId)
  scope: sbNamespace
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', sbDataSenderRoleId)
    principalId: agentIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource workerSbReceiver 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(sbNamespace.id, workerIdentityPrincipalId, sbDataReceiverRoleId)
  scope: sbNamespace
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', sbDataReceiverRoleId)
    principalId: workerIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Worker also needs to send (outbox relay sends to DLQ recovery)
resource workerSbSender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(sbNamespace.id, workerIdentityPrincipalId, sbDataSenderRoleId)
  scope: sbNamespace
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', sbDataSenderRoleId)
    principalId: workerIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

output namespaceId string = sbNamespace.id
output namespaceName string = sbNamespace.name
output namespaceFqdn string = '${sbNamespace.name}.servicebus.windows.net'
output queueName string = domainEventsQueue.name
