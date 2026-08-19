// Private Container Apps runtime for the prompt intake MCP boundary.
targetScope = 'resourceGroup'

param location string
param tags object
param environmentName string
param appName string
param subnetId string
param image string
param acrLoginServer string
param mcpIdentityId string
param mcpIdentityClientId string
param tenantId string
param mcpAppClientId string
param appInsightsConnectionString string
param logAnalyticsWorkspaceCustomerId string
@secure()
param logAnalyticsSharedKey string

param cosmosEndpoint string
param cosmosDatabase string
param cosmosRequestsContainer string
param cosmosTemplatesContainer string
param cosmosIdempotencyContainer string
param serviceBusNamespace string
param serviceBusQueue string
param blobEndpoint string
param artifactsContainer string
param environmentNameTag string

resource mcpEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
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
    vnetConfiguration: {
      internal: true
      infrastructureSubnetId: subnetId
    }
  }
}

var mcpAudience = 'api://${mcpAppClientId}'
var mcpServerUrl = 'https://${appName}.${mcpEnvironment.properties.defaultDomain}/mcp'

resource mcpApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  tags: union(tags, { 'azd-service-name': 'intake-mcp' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${mcpIdentityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: mcpEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        // The environment has an internal load balancer, so "external" means
        // VNet-reachable rather than internet-reachable.
        external: true
        allowInsecure: false
        targetPort: 8080
        transport: 'auto'
      }
      registries: [
        {
          server: acrLoginServer
          identity: mcpIdentityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'intake-mcp'
          image: image
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: appInsightsConnectionString
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: mcpIdentityClientId
            }
            {
              name: 'INTAKE_ENVIRONMENT'
              value: environmentNameTag
            }
            {
              name: 'INTAKE_HOSTED_TENANT_ID'
              value: tenantId
            }
            {
              name: 'INTAKE_HOSTED_AGENT_IDENTITY'
              value: 'prompt-intake-agent'
            }
            {
              name: 'INTAKE_PERSISTENCE_BACKEND'
              value: 'cosmos'
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
              name: 'INTAKE_COSMOS_REQUESTS_CONTAINER'
              value: cosmosRequestsContainer
            }
            {
              name: 'INTAKE_COSMOS_TEMPLATES_CONTAINER'
              value: cosmosTemplatesContainer
            }
            {
              name: 'INTAKE_COSMOS_IDEMPOTENCY_CONTAINER'
              value: cosmosIdempotencyContainer
            }
            {
              name: 'INTAKE_SERVICEBUS_BACKEND'
              value: 'azure'
            }
            {
              name: 'INTAKE_SERVICEBUS_NAMESPACE'
              value: serviceBusNamespace
            }
            {
              name: 'INTAKE_SERVICEBUS_QUEUE'
              value: serviceBusQueue
            }
            {
              name: 'INTAKE_BLOB_BACKEND'
              value: 'azure'
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
              name: 'INTAKE_MCP_TENANT_ID'
              value: tenantId
            }
            {
              name: 'INTAKE_MCP_AUDIENCE'
              value: mcpAudience
            }
            {
              name: 'INTAKE_MCP_SERVER_URL'
              value: mcpServerUrl
            }
            {
              name: 'INTAKE_MCP_REQUIRED_SCOPE'
              value: 'access_as_user'
            }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8080
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/readiness'
                port: 8080
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 5
      }
    }
  }
}

output environmentId string = mcpEnvironment.id
output environmentDefaultDomain string = mcpEnvironment.properties.defaultDomain
output environmentStaticIp string = mcpEnvironment.properties.staticIp
output appId string = mcpApp.id
output appName string = mcpApp.name
output appFqdn string = mcpApp.properties.configuration.ingress.fqdn
output serverUrl string = mcpServerUrl
output audience string = mcpAudience
