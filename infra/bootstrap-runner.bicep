// Explicit, out-of-band bootstrap for the private GitHub Actions runner.
// This template is never invoked by azd provision, preventing the runner from
// updating the Container Apps Job that is currently executing a deployment.
targetScope = 'resourceGroup'

@minLength(1)
param environmentName string

@minLength(1)
param location string

@minLength(1)
param githubRepoOwner string

@minLength(1)
param githubRepoName string

@minLength(1)
@description('The image produced by the bootstrap ACR build stage.')
param runnerImage string

@secure()
@description('Fine-grained repository PAT supplied only for the job creation/rotation stage.')
param githubPat string

@description('Creates or updates the event-driven job only after a real image and PAT are available.')
param deployRunnerJob bool = false

// The dev architecture is private-only: the runner registry is reachable
// exclusively through its private endpoint, and the runner is the sole path
// to the VNet-locked application resources. There is deliberately no
// `deployPrivateEndpoints` parameter to turn that off — a public fallback
// would contradict the ACLs the application templates now depend on. ARM
// rejects the removed parameter outright if a caller still passes it.

param runnerLabel string = 'aca-intake-dev'

var tags = {
  'azd-env-name': environmentName
  project: 'intake-agent'
  environment: environmentName
  'managed-by': 'azd-bicep'
}
// Preserve the unique suffix used by the original subscription-scope template.
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var acrName = 'acr${resourceToken}'
var environmentId = resourceId('Microsoft.App/managedEnvironments', 'cae-intake-${environmentName}')
var privateEndpointSubnetId = resourceId('Microsoft.Network/virtualNetworks/subnets', 'vnet-intake-${environmentName}', 'snet-private-endpoints')
var acrPrivateDnsZoneId = resourceId('Microsoft.Network/privateDnsZones', 'privatelink.azurecr.io')

module runnerIdentity 'modules/runner-identity.bicep' = {
  name: 'runnerIdentity'
  params: {
    location: location
    tags: tags
    environmentName: environmentName
  }
}

module runnerAcr 'modules/runner-acr.bicep' = {
  name: 'runnerAcr'
  params: {
    location: location
    tags: tags
    acrName: acrName
    deployPrivateEndpoints: true
    acrAllowPublicNetworkAccessForBootstrap: false
    runnerIdentityPrincipalId: runnerIdentity.outputs.principalId
  }
}

module runnerAcrPrivateEndpoint 'modules/runner-acr-private-endpoint.bicep' = {
  name: 'runnerAcrPrivateEndpoint'
  params: {
    location: location
    tags: tags
    acrName: runnerAcr.outputs.acrName
    acrId: runnerAcr.outputs.acrId
    privateEndpointSubnetId: privateEndpointSubnetId
    acrPrivateDnsZoneId: acrPrivateDnsZoneId
  }
}

module runnerJob 'modules/runner-job.bicep' = if (deployRunnerJob) {
  name: 'runnerJob'
  params: {
    location: location
    tags: tags
    jobName: 'job-intake-runner-${environmentName}'
    environmentId: environmentId
    runnerIdentityId: runnerIdentity.outputs.id
    acrLoginServer: runnerAcr.outputs.loginServer
    githubPat: githubPat
    runnerImage: runnerImage
    githubRepoOwner: githubRepoOwner
    githubRepoName: githubRepoName
    runnerLabel: runnerLabel
    environmentNameTag: environmentName
  }
}

output AZURE_RUNNER_ACR_NAME string = runnerAcr.outputs.acrName
output AZURE_RUNNER_ACR_LOGIN_SERVER string = runnerAcr.outputs.loginServer
output AZURE_RUNNER_JOB_NAME string = 'job-intake-runner-${environmentName}'
