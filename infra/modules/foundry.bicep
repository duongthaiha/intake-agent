// Azure AI Foundry module — Hub, Project, and AI Services account
//
// ⚠️  GATED — deployFoundry must be true in main.bicep parameters.
// ⚠️  REQUIRES Microsoft.MachineLearningServices provider registration.
// ⚠️  Hosted Agent model deployment is NOT included here:
//      - Model selection and TPM quota must be confirmed before deploying.
//      - Use the Foundry portal or CLI to create model deployments after provisioning.
//      - Gate model-deployment Bicep behind a separate parameter once model/quota is confirmed.
//
// References:
//   ARM/Bicep: https://learn.microsoft.com/azure/templates/microsoft.machinelearningservices/workspaces
//   Quickstart: https://github.com/Azure/azure-quickstart-templates/tree/master/quickstarts/microsoft.machinelearningservices/aifoundry-basics
targetScope = 'resourceGroup'

param location string
param tags object
param hubName string
param projectName string
param aiServicesName string
param storageAccountId string
param keyVaultId string
param appInsightsId string
param agentIdentityId string
param agentIdentityPrincipalId string

// ---------------------------------------------------------------------------
// AI Services account (multi-model, kind: AIServices)
// ---------------------------------------------------------------------------

resource aiServices 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: aiServicesName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: aiServicesName
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
    networkAcls: {
      defaultAction: 'Allow'
      ipRules: []
    }
  }
}

// ---------------------------------------------------------------------------
// Foundry Hub (kind: Hub)
// Links storage, Key Vault, App Insights, and AI Services as connections.
// ---------------------------------------------------------------------------

resource foundryHub 'Microsoft.MachineLearningServices/workspaces@2024-10-01' = {
  name: hubName
  location: location
  tags: tags
  kind: 'Hub'
  identity: {
    type: 'SystemAssigned'
  }
  sku: {
    name: 'Basic'
    tier: 'Basic'
  }
  properties: {
    storageAccount: storageAccountId
    keyVault: keyVaultId
    applicationInsights: appInsightsId
    hbiWorkspace: false
    publicNetworkAccess: 'Enabled'
  }
}

// AI Services connection on the hub
resource hubAiServicesConnection 'Microsoft.MachineLearningServices/workspaces/connections@2024-10-01' = {
  parent: foundryHub
  name: 'aiservices-connection'
  properties: {
    category: 'AIServices'
    target: aiServices.properties.endpoint
    authType: 'AAD'
    isSharedToAll: true
    metadata: {
      ApiType: 'Azure'
      ResourceId: aiServices.id
    }
  }
}

// ---------------------------------------------------------------------------
// Foundry Project (kind: Project, child of Hub)
// ---------------------------------------------------------------------------

resource foundryProject 'Microsoft.MachineLearningServices/workspaces@2024-10-01' = {
  name: projectName
  location: location
  tags: tags
  kind: 'Project'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${agentIdentityId}': {}
    }
  }
  sku: {
    name: 'Basic'
    tier: 'Basic'
  }
  properties: {
    hubResourceId: foundryHub.id
    publicNetworkAccess: 'Enabled'
  }
}

// ---------------------------------------------------------------------------
// RBAC — Foundry roles for agent managed identity
// ---------------------------------------------------------------------------

// Azure AI Developer role on the project (allows agent management + invocation)
var aiDeveloperRoleId = '64702f94-c441-49e6-a78b-ef80e0188fee'

resource agentAiDeveloper 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryProject.id, agentIdentityPrincipalId, aiDeveloperRoleId)
  scope: foundryProject
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', aiDeveloperRoleId)
    principalId: agentIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Cognitive Services OpenAI User (model invocation)
var cogServicesUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

resource agentCogServicesUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiServices.id, agentIdentityPrincipalId, cogServicesUserRoleId)
  scope: aiServices
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cogServicesUserRoleId)
    principalId: agentIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

output hubId string = foundryHub.id
output hubName string = foundryHub.name
output projectId string = foundryProject.id
output projectName string = foundryProject.name
output aiServicesId string = aiServices.id
output aiServicesName string = aiServices.name
output aiServicesEndpoint string = aiServices.properties.endpoint
