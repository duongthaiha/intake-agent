// Runner ACR — Azure Container Registry hosting the ephemeral GitHub Actions
// Container Apps Job runner image. Premium SKU is required for private
// endpoints. Azure AD-only authentication (no admin user, no anonymous pull).
//
// Bootstrap note: `az acr build` needs a network path to the registry to
// push the built image. With deployPrivateEndpoints=true this registry has
// no public network access, so the *very first* image push cannot originate
// from the public internet (same chicken-and-egg as the runner itself: no
// runner exists yet to build from inside the VNet). Operators must run the
// one-time bootstrap with `acrAllowPublicNetworkAccessForBootstrap=true`
// (still AAD-auth-only, never anonymous), push the image via
// scripts/azure/bootstrap-runner.sh, then redeploy with the flag reverted to
// false. See scripts/azure/bootstrap-runner.sh and the deploy runbook.
targetScope = 'resourceGroup'

param location string
param tags object
param acrName string
param deployPrivateEndpoints bool
@description('Temporary escape hatch for the one-time image bootstrap only. Must be reverted to false immediately after the first push. Registry remains AAD-auth-only regardless of this setting.')
param acrAllowPublicNetworkAccessForBootstrap bool = false
@description('Principal ID of the runner UAMI — granted AcrPull only.')
param runnerIdentityPrincipalId string

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  tags: tags
  sku: {
    name: 'Premium'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: (deployPrivateEndpoints && !acrAllowPublicNetworkAccessForBootstrap) ? 'Disabled' : 'Enabled'
    networkRuleBypassOptions: 'AzureServices'
    // Regional data endpoints disabled — keeps private DNS to a single
    // `privatelink.azurecr.io` zone (no additional `{region}.data.privatelink...` zone needed).
    dataEndpointEnabled: false
  }
}

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d' // AcrPull

resource runnerAcrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, runnerIdentityPrincipalId, acrPullRoleId)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: runnerIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output acrId string = acr.id
output acrName string = acr.name
output loginServer string = acr.properties.loginServer
