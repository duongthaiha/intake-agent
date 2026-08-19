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
param mcpIdentityId string
param mcpIdentityClientId string
param storageEndpoint string
param evalContainer string
param cosmosEndpoint string
param cosmosDatabase string
param cosmosRequestsContainer string
param cosmosTemplatesContainer string
param cosmosIdempotencyContainer string
param serviceBusNamespace string
param serviceBusQueue string
param appInsightsConnectionString string
param mcpAudience string
param mcpScope string
param tenantId string
@description('Bootstrap image used at provision time. azd deploy replaces it with the immutable image built from Dockerfile.mcp.')
param mcpBootstrapImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld@sha256:e9b3e7c34664c7cffd7144864b0e4eec369bfde80068f9095dc63b37058bec48'
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

resource mcpApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-intake-mcp-${environmentNameTag}'
  location: location
  tags: union(tags, { 'azd-service-name': 'mcp' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${mcpIdentityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: cae.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
      maxInactiveRevisions: 3
    }
    template: {
      containers: [
        {
          name: 'mcp'
          image: mcpBootstrapImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'AZURE_CLIENT_ID', value: mcpIdentityClientId }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
            { name: 'INTAKE_ENVIRONMENT', value: environmentNameTag }
            { name: 'INTAKE_PERSISTENCE_BACKEND', value: 'cosmos' }
            { name: 'INTAKE_COSMOS_ENDPOINT', value: cosmosEndpoint }
            { name: 'INTAKE_COSMOS_DATABASE', value: cosmosDatabase }
            { name: 'INTAKE_COSMOS_REQUESTS_CONTAINER', value: cosmosRequestsContainer }
            { name: 'INTAKE_COSMOS_TEMPLATES_CONTAINER', value: cosmosTemplatesContainer }
            { name: 'INTAKE_COSMOS_IDEMPOTENCY_CONTAINER', value: cosmosIdempotencyContainer }
            { name: 'INTAKE_BLOB_BACKEND', value: 'azure' }
            { name: 'INTAKE_BLOB_ENDPOINT', value: storageEndpoint }
            { name: 'INTAKE_BLOB_CONTAINER_ARTIFACTS', value: 'request-artifacts' }
            { name: 'INTAKE_SERVICEBUS_BACKEND', value: 'azure' }
            { name: 'INTAKE_SERVICEBUS_NAMESPACE', value: serviceBusNamespace }
            { name: 'INTAKE_SERVICEBUS_QUEUE', value: serviceBusQueue }
            { name: 'INTAKE_MCP_AUDIENCE', value: mcpAudience }
            { name: 'INTAKE_MCP_REQUIRED_SCOPE', value: mcpScope }
            { name: 'INTAKE_MCP_TENANT_ID', value: tenantId }
            { name: 'INTAKE_MCP_ISSUER', value: '${environment().authentication.loginEndpoint}${tenantId}/v2.0' }
          ]
          probes: [
            {
              type: 'Startup'
              httpGet: { path: '/health', port: 8000, scheme: 'HTTP' }
              initialDelaySeconds: 2
              periodSeconds: 5
              timeoutSeconds: 2
              failureThreshold: 24
            }
            {
              type: 'Liveness'
              httpGet: { path: '/health', port: 8000, scheme: 'HTTP' }
              periodSeconds: 20
              timeoutSeconds: 3
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: { path: '/readiness', port: 8000, scheme: 'HTTP' }
              periodSeconds: 10
              timeoutSeconds: 3
              failureThreshold: 3
              successThreshold: 1
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 5
        rules: [
          {
            name: 'http-concurrency'
            http: {
              metadata: {
                concurrentRequests: '25'
              }
            }
          }
        ]
      }
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
output mcpAppId string = mcpApp.id
output mcpAppName string = mcpApp.name
output mcpFqdn string = mcpApp.properties.configuration.ingress.fqdn
output mcpEndpoint string = 'https://${mcpApp.properties.configuration.ingress.fqdn}/mcp'
