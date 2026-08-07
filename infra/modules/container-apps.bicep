// Container Apps module — managed environment + evaluation job definition
// The job is defined as a placeholder; the eval container image is published by Switch.
targetScope = 'resourceGroup'

param location string
param tags object
param environmentName string
param evalJobName string
param logAnalyticsWorkspaceCustomerId string
@secure()
param logAnalyticsSharedKey string
param evalIdentityId string
param evalIdentityClientId string
param storageEndpoint string
param evalContainer string
param appInsightsConnectionString string
@description('VNet subnet ID for the Container Apps environment. Leave empty for public deployment.')
param subnetId string = ''
param environmentNameTag string

// ---------------------------------------------------------------------------
// Container Apps managed environment
// ---------------------------------------------------------------------------

resource cae 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsWorkspaceCustomerId
        #disable-next-line BCP036
        sharedKey: logAnalyticsSharedKey
      }
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    vnetConfiguration: !empty(subnetId) ? {
      internal: false
      infrastructureSubnetId: subnetId
    } : null
  }
}

// ---------------------------------------------------------------------------
// Evaluation job — placeholder manifest
// Replace the image with the published eval container after Switch creates it.
// ---------------------------------------------------------------------------

resource evalJob 'Microsoft.App/jobs@2024-03-01' = {
  name: evalJobName
  location: location
  tags: union(tags, { 'azd-service-name': 'eval' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${evalIdentityId}': {}
    }
  }
  properties: {
    environmentId: cae.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 3600
      replicaRetryLimit: 1
    }
    template: {
      containers: [
        {
          name: 'eval'
          // Placeholder image — replace with actual eval container image after Switch publishes it.
          // Set via azd or pipeline: INTAKE_EVAL_IMAGE env var.
          image: 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
          resources: {
            cpu: json('0.5')
            memory: '1.0Gi'
          }
          env: [
            {
              name: 'INTAKE_EVAL_STORAGE_ENDPOINT'
              value: storageEndpoint
            }
            {
              name: 'INTAKE_EVAL_CONTAINER'
              value: evalContainer
            }
            {
              name: 'INTAKE_APPINSIGHTS_CONNECTION'
              value: appInsightsConnectionString
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: evalIdentityClientId
            }
            {
              name: 'INTAKE_ENVIRONMENT'
              value: environmentNameTag
            }
          ]
        }
      ]
      initContainers: []
    }
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

output environmentId string = cae.id
output environmentName string = cae.name
output evalJobId string = evalJob.id
output evalJobName string = evalJob.name
