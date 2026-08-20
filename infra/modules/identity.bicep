@description('Azure region for all managed identities.')
param location string

@description('Short, globally consistent resource-name suffix.')
param suffix string

@description('Common resource tags.')
param tags object

var identityDefinitions = [
  {
    key: 'commandService'
    name: 'id-intake-command-${suffix}'
  }
  {
    key: 'outboxWorker'
    name: 'id-intake-outbox-${suffix}'
  }
  {
    key: 'notificationWorker'
    name: 'id-intake-notification-${suffix}'
  }
  {
    key: 'integrationWorker'
    name: 'id-intake-integration-${suffix}'
  }
  {
    key: 'completionWorker'
    name: 'id-intake-completion-${suffix}'
  }
  {
    key: 'retentionWorker'
    name: 'id-intake-retention-${suffix}'
  }
  {
    key: 'evaluationJob'
    name: 'id-intake-evaluation-${suffix}'
  }
  {
    key: 'foundryConfigurator'
    name: 'id-intake-foundry-config-${suffix}'
  }
]

resource identities 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = [
  for definition in identityDefinitions: {
    name: definition.name
    location: location
    tags: tags
  }
]

output identities object = {
  commandService: {
    id: identities[0].id
    name: identities[0].name
    clientId: identities[0].properties.clientId
    principalId: identities[0].properties.principalId
  }
  outboxWorker: {
    id: identities[1].id
    name: identities[1].name
    clientId: identities[1].properties.clientId
    principalId: identities[1].properties.principalId
  }
  notificationWorker: {
    id: identities[2].id
    name: identities[2].name
    clientId: identities[2].properties.clientId
    principalId: identities[2].properties.principalId
  }
  integrationWorker: {
    id: identities[3].id
    name: identities[3].name
    clientId: identities[3].properties.clientId
    principalId: identities[3].properties.principalId
  }
  completionWorker: {
    id: identities[4].id
    name: identities[4].name
    clientId: identities[4].properties.clientId
    principalId: identities[4].properties.principalId
  }
  retentionWorker: {
    id: identities[5].id
    name: identities[5].name
    clientId: identities[5].properties.clientId
    principalId: identities[5].properties.principalId
  }
  evaluationJob: {
    id: identities[6].id
    name: identities[6].name
    clientId: identities[6].properties.clientId
    principalId: identities[6].properties.principalId
  }
  foundryConfigurator: {
    id: identities[7].id
    name: identities[7].name
    clientId: identities[7].properties.clientId
    principalId: identities[7].properties.principalId
  }
}
