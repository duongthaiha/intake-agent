// Azure Functions module — Flex Consumption plan (FC1) with managed identity
// Falls back to documented workaround if FC1 unavailable in the target region.
targetScope = 'resourceGroup'

param location string
param tags object
param functionAppName string
param planName string
param storageAccountName string
param appInsightsConnectionString string
param workerIdentityId string
param workerIdentityClientId string
param cosmosEndpoint string
param cosmosDatabase string
param serviceBusNamespace string
param serviceBusQueue string
param blobEndpoint string
param artifactsContainer string
param keyVaultUri string
param environmentName string
@description('VNet integration subnet resource ID. Leave empty to skip VNet integration.')
param vnetIntegrationSubnetId string = ''


// ---------------------------------------------------------------------------
// Flex Consumption App Service Plan (FC1)
// NOTE: The only deployable plan type in this subscription (0 VM quota for Y1/Dynamic).
// FC1 uses Container Apps Legion infrastructure and requires blob-based deployment.
// Blob deployment from outside Azure is currently blocked by Azure Policy (publicNetworkAccess:Disabled).
// Workaround: deploy from Azure Cloud Shell or request Y1 VM quota increase.
// ---------------------------------------------------------------------------

resource flexPlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: planName
  location: location
  tags: tags
  kind: 'functionapp'
  sku: {
    name: 'FC1'
    tier: 'FlexConsumption'
  }
  properties: {
    reserved: true
  }
}

// ---------------------------------------------------------------------------
// Function App
// ---------------------------------------------------------------------------

resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: functionAppName
  location: location
  tags: union(tags, { 'azd-service-name': 'workers' })
  kind: 'functionapp,linux'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${workerIdentityId}': {}
    }
  }
  properties: {
    serverFarmId: flexPlan.id
    reserved: true
    httpsOnly: true
    keyVaultReferenceIdentity: workerIdentityId
    virtualNetworkSubnetId: !empty(vnetIntegrationSubnetId) ? vnetIntegrationSubnetId : null
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${blobEndpoint}deploymentpackage'
          authentication: {
            type: 'UserAssignedIdentity'
            userAssignedIdentityResourceId: workerIdentityId
          }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: 100
        // 512 MB is the cost-optimised POC setting; 2048 MB was only needed
        // when alwaysReady was required to work around missing Data Owner.
        // Now that Data Owner is assigned, the FC1 scale controller reads queue
        // depth accurately and starts SB-group instances on demand.
        instanceMemoryMB: 512
      }
      runtime: {
        name: 'python'
        version: '3.11'
      }
    }
    siteConfig: {
      appSettings: [
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsightsConnectionString
        }
        {
          name: 'INTAKE_COSMOS_ENDPOINT'
          value: cosmosEndpoint
        }
        {
          name: 'INTAKE_COSMOS_DATABASE'
          value: cosmosDatabase
        }
        {
          name: 'INTAKE_SERVICEBUS_NAMESPACE__fullyQualifiedNamespace'
          value: serviceBusNamespace
        }
        {
          name: 'INTAKE_SERVICEBUS_QUEUE'
          value: serviceBusQueue
        }
        {
          name: 'INTAKE_BLOB_ENDPOINT'
          value: blobEndpoint
        }
        {
          name: 'INTAKE_BLOB_CONTAINER_ARTIFACTS'
          value: artifactsContainer
        }
        {
          name: 'INTAKE_KEYVAULT_URI'
          value: keyVaultUri
        }
        {
          name: 'INTAKE_ENVIRONMENT'
          value: environmentName
        }
        {
          name: 'AZURE_CLIENT_ID'
          value: workerIdentityClientId
        }
        // Required for WebJobs host health check — uses identity-based auth (no shared key)
        {
          name: 'AzureWebJobsStorage__accountName'
          value: storageAccountName
        }
        {
          name: 'AzureWebJobsStorage__credential'
          value: 'managedidentity'
        }
        {
          name: 'AzureWebJobsStorage__clientId'
          value: workerIdentityClientId
        }
      ]
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
    }
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

output appId string = functionApp.id
output appName string = functionApp.name
output defaultHostName string = functionApp.properties.defaultHostName
