targetScope = 'resourceGroup'

@description('Existing Key Vault name.')
param vaultName string

@description('Secret name.')
param secretName string

@secure()
@description('Secret value. Azure deployment history redacts secure parameters.')
param secretValue string

resource vault 'Microsoft.KeyVault/vaults@2026-02-01' existing = {
  name: vaultName
}

resource secret 'Microsoft.KeyVault/vaults/secrets@2026-02-01' = {
  parent: vault
  name: secretName
  properties: {
    value: secretValue
  }
}

output secretUriWithVersion string = secret.properties.secretUriWithVersion
