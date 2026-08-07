// Identity module — user-assigned managed identities (one per workload trust boundary)
targetScope = 'resourceGroup'

param location string
param tags object
param environmentName string

// ---------------------------------------------------------------------------
// User-assigned managed identities
// ---------------------------------------------------------------------------

resource agentIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-intake-agent-${environmentName}'
  location: location
  tags: tags
}

resource workerIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-intake-worker-${environmentName}'
  location: location
  tags: tags
}

resource evalIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-intake-eval-${environmentName}'
  location: location
  tags: tags
}

resource notifyIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-intake-notify-${environmentName}'
  location: location
  tags: tags
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

output agentIdentityId string = agentIdentity.id
output agentIdentityPrincipalId string = agentIdentity.properties.principalId
output agentIdentityClientId string = agentIdentity.properties.clientId

output workerIdentityId string = workerIdentity.id
output workerIdentityPrincipalId string = workerIdentity.properties.principalId
output workerIdentityClientId string = workerIdentity.properties.clientId

output evalIdentityId string = evalIdentity.id
output evalIdentityPrincipalId string = evalIdentity.properties.principalId
output evalIdentityClientId string = evalIdentity.properties.clientId

output notifyIdentityId string = notifyIdentity.id
output notifyIdentityPrincipalId string = notifyIdentity.properties.principalId
output notifyIdentityClientId string = notifyIdentity.properties.clientId
