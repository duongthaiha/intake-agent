// Dedicated identity for the ephemeral CI/CD runner. It intentionally has no
// deployment, Key Vault, or application data-plane permissions.
targetScope = 'resourceGroup'

param location string
param tags object
param environmentName string

resource runnerIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-intake-runner-${environmentName}'
  location: location
  tags: tags
}

output id string = runnerIdentity.id
output principalId string = runnerIdentity.properties.principalId
