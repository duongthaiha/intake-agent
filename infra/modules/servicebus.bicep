// Service Bus module — Standard namespace, queues for domain events and DLQ recovery
targetScope = 'resourceGroup'

param location string
param tags object
param namespaceName string
param mcpIdentityPrincipalId string
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
    disableLocalAuth: true  // Require identity-based auth; SAS connection strings disabled
    // Private endpoints require Premium. Keep Standard public with local auth
    // disabled and managed-identity RBAC to preserve the low-cost POC topology.
    publicNetworkAccess: 'Enabled'
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

// Durable outbox target. The original domain-events queue is retained because
// duplicate detection cannot be enabled in place. Stable outbox item IDs are
// sent as Service Bus MessageId values, giving at-least-once dispatch bounded
// duplicate suppression without destructive queue recreation.
resource durableDomainEventsQueue 'Microsoft.ServiceBus/namespaces/queues@2022-10-01-preview' = {
  parent: sbNamespace
  name: 'domain-events-durable'
  properties: {
    maxDeliveryCount: 10
    lockDuration: 'PT5M'
    defaultMessageTimeToLive: 'P14D'
    deadLetteringOnMessageExpiration: true
    enablePartitioning: false
    requiresDuplicateDetection: true
    duplicateDetectionHistoryTimeWindow: 'P1D'
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

resource documentGenerationQueue 'Microsoft.ServiceBus/namespaces/queues@2022-10-01-preview' = {
  parent: sbNamespace
  name: 'document-generation'
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

resource notificationQueue 'Microsoft.ServiceBus/namespaces/queues@2022-10-01-preview' = {
  parent: sbNamespace
  name: 'notification-queue'
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

// ---------------------------------------------------------------------------
// RBAC
// ---------------------------------------------------------------------------

var sbDataSenderRoleId = '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39'
// FC1 SB trigger scale controller requires Data Owner (or a custom role with
// Microsoft.ServiceBus/namespaces/*/read) for accurate queue-depth scaling.
// Without it the extension silently falls back to peek-based estimation and
// SB-group instances may never start.  Ref: Azure Functions SB trigger docs –
// "Identity-based connections" section.
var sbDataOwnerRoleId = '090c5cfd-751d-490a-894a-3ce6f1109419'

resource mcpSbSender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(sbNamespace.id, mcpIdentityPrincipalId, sbDataSenderRoleId)
  scope: sbNamespace
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', sbDataSenderRoleId)
    principalId: mcpIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Worker requires Data Owner so the FC1 scale controller can read queue metrics
// (includes Send + Receive + Manage). Replaces the separate Sender/Receiver pair.
resource workerSbOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(sbNamespace.id, workerIdentityPrincipalId, sbDataOwnerRoleId)
  scope: sbNamespace
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', sbDataOwnerRoleId)
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
output queueName string = durableDomainEventsQueue.name
output documentGenerationQueueName string = documentGenerationQueue.name
output notificationQueueName string = notificationQueue.name
