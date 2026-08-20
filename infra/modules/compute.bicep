@description('Deploy runtime resource placeholders only after immutable images are available.')
param deployWorkloads bool = false

@description('Deploy asynchronous worker applications.')
param deployWorkers bool = deployWorkloads

@description('Deploy the evaluation job.')
param deployEvaluation bool = deployWorkloads

@description('Deploy the private Foundry configuration job.')
param deployFoundryConfiguration bool = false

@description('Azure region for runtime resources.')
param location string

@description('Short, globally consistent resource-name suffix.')
param suffix string

@description('Common resource tags.')
param tags object

@description('Dedicated Container Apps managed environment.')
param environment object

@description('Azure Container Registry.')
param registry object

@description('Managed workload identities.')
param identities object

@description('Application configuration values.')
param configuration object

@description('Immutable command-service container image reference.')
param commandServiceImage string = 'runtime-artifact-required'

@description('Immutable worker container image reference.')
param workersImage string = 'runtime-artifact-required'

@description('Immutable evaluation-job container image reference.')
param evaluationImage string = 'runtime-artifact-required'

@description('Immutable Foundry configuration container image reference.')
param foundryConfigurationImage string = 'runtime-artifact-required'

@description('Immutable Foundry Hosted Agent image reference.')
param hostedAgentImage string = 'runtime-artifact-required'

var commandServiceName = 'ca-intake-command-${suffix}'

resource commandService 'Microsoft.App/containerApps@2026-01-01' = if (deployWorkloads) {
  name: commandServiceName
  location: location
  tags: union(tags, {
    'azd-service-name': 'command-service'
  })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identities.commandService.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        allowInsecure: false
        external: false
        targetPort: 8000
        transport: 'http'
      }
      registries: [
        {
          identity: identities.commandService.id
          server: registry.loginServer
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'command-service'
          image: commandServiceImage
          env: [
            {
              name: 'AZURE_CLIENT_ID'
              value: identities.commandService.clientId
            }
            {
              name: 'COSMOS_ENDPOINT'
              value: configuration.cosmosEndpoint
            }
            {
              name: 'COSMOS_DATABASE'
              value: configuration.cosmosDatabase
            }
            {
              name: 'SERVICE_BUS_NAMESPACE'
              value: '${configuration.serviceBusNamespace}.servicebus.windows.net'
            }
            {
              name: 'SERVICE_BUS_TOPIC'
              value: configuration.serviceBusTopic
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: configuration.applicationInsightsConnectionString
            }
            {
              name: 'APPLICATIONINSIGHTS_AUTHENTICATION_STRING'
              value: 'Authorization=AAD;ClientId=${identities.commandService.clientId}'
            }
            {
              name: 'STORAGE_BLOB_ENDPOINT'
              value: configuration.storageBlobEndpoint
            }
            {
              name: 'ENTRA_TENANT_ID'
              value: configuration.entraTenantId
            }
            {
              name: 'MCP_AUDIENCE'
              value: configuration.mcpAudience
            }
            {
              name: 'MCP_REQUIRED_SCOPE'
              value: configuration.mcpRequiredScope
            }
            {
              name: 'MCP_AUTHORIZED_CLIENT_IDS'
              value: join(configuration.mcpAuthorizedClientIds, ',')
            }
            {
              name: 'MCP_RESOURCE_SERVER_URL'
              value: 'https://${commandServiceName}.${environment.defaultDomain}'
            }
            {
              name: 'DEFAULT_REVIEWER_ID'
              value: 'reviewer-default'
            }
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 10
      }
    }
  }
}

var workerDefinitions = [
  {
    name: 'outbox'
    subscription: ''
    identity: identities.outboxWorker
  }
  {
    name: 'notification'
    subscription: 'notifications'
    identity: identities.notificationWorker
  }
  {
    name: 'integration'
    subscription: 'integrations'
    identity: identities.integrationWorker
  }
  {
    name: 'completion'
    subscription: 'completion'
    identity: identities.completionWorker
  }
  {
    name: 'retention'
    subscription: 'retention'
    identity: identities.retentionWorker
  }
]

resource workers 'Microsoft.App/containerApps@2026-01-01' = [
  for worker in workerDefinitions: if (deployWorkers) {
    name: 'ca-${worker.name}-${suffix}'
    location: location
    kind: 'functionapp'
    tags: union(tags, {
      'azd-service-name': '${worker.name}-worker'
    })
    identity: {
      type: 'UserAssigned'
      userAssignedIdentities: {
        '${worker.identity.id}': {}
      }
    }
    properties: {
      managedEnvironmentId: environment.id
      workloadProfileName: 'Consumption'
      configuration: {
        activeRevisionsMode: 'Single'
        registries: [
          {
            identity: worker.identity.id
            server: registry.loginServer
          }
        ]
      }
      template: {
        containers: [
          {
            name: '${worker.name}-worker'
            image: workersImage
            env: [
              {
                name: 'WORKER_KIND'
                value: worker.name
              }
              {
                name: 'AZURE_CLIENT_ID'
                value: worker.identity.clientId
              }
              {
                name: 'COSMOS_ENDPOINT'
                value: configuration.cosmosEndpoint
              }
              {
                name: 'COSMOS_DATABASE'
                value: configuration.cosmosDatabase
              }
              {
                name: 'SERVICE_BUS_NAMESPACE'
                value: '${configuration.serviceBusNamespace}.servicebus.windows.net'
              }
              {
                name: 'SERVICE_BUS_TOPIC'
                value: configuration.serviceBusTopic
              }
              {
                name: 'SERVICE_BUS_SUBSCRIPTION'
                value: worker.subscription
              }
              {
                name: 'INTAKE_SERVICEBUS_NAMESPACE__fullyQualifiedNamespace'
                value: '${configuration.serviceBusNamespace}.servicebus.windows.net'
              }
              {
                name: 'STORAGE_BLOB_ENDPOINT'
                value: configuration.storageBlobEndpoint
              }
              {
                name: 'ENTRA_TENANT_ID'
                value: configuration.entraTenantId
              }
              {
                name: 'DEFAULT_REVIEWER_ID'
                value: 'reviewer-default'
              }
              {
                name: 'AzureWebJobsStorage__accountName'
                value: configuration.storageAccountName
              }
              {
                name: 'AzureWebJobsStorage__credential'
                value: 'managedidentity'
              }
              {
                name: 'AzureWebJobsStorage__clientId'
                value: worker.identity.clientId
              }
              {
                name: 'FUNCTIONS_WORKER_RUNTIME'
                value: 'python'
              }
              {
                name: 'AzureWebJobsFeatureFlags'
                value: 'EnableWorkerIndexing'
              }
              {
                name: 'KEY_VAULT_URI'
                value: configuration.keyVaultUri
              }
              {
                name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
                value: configuration.applicationInsightsConnectionString
              }
              {
                name: 'APPLICATIONINSIGHTS_AUTHENTICATION_STRING'
                value: 'Authorization=AAD;ClientId=${worker.identity.clientId}'
              }
            ]
            resources: {
              cpu: json('0.5')
              memory: '1Gi'
            }
          }
        ]
        scale: {
          minReplicas: 0
          maxReplicas: 10
        }
      }
    }
  }
]

resource evaluationJob 'Microsoft.App/jobs@2025-01-01' = if (deployEvaluation) {
  name: 'caj-intake-evaluation-${suffix}'
  location: location
  tags: union(tags, {
    'azd-service-name': 'evaluation-job'
  })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identities.evaluationJob.id}': {}
    }
  }
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      replicaRetryLimit: 0
      replicaTimeout: 3600
      triggerType: 'Manual'
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: [
        {
          identity: identities.evaluationJob.id
          server: registry.loginServer
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'evaluation'
          image: evaluationImage
          env: [
            {
              name: 'AZURE_CLIENT_ID'
              value: identities.evaluationJob.clientId
            }
            {
              name: 'FOUNDRY_PROJECT_ENDPOINT'
              value: configuration.foundryProjectEndpoint
            }
            {
              name: 'STORAGE_ACCOUNT_NAME'
              value: configuration.storageAccountName
            }
            {
              name: 'STORAGE_BLOB_ENDPOINT'
              value: configuration.storageBlobEndpoint
            }
            {
              name: 'EVALUATION_COMMIT_SHA'
              value: configuration.evaluationCommitSha
            }
            {
              name: 'EVALUATION_RESULTS_CONTAINER'
              value: 'evaluation-datasets'
            }
            {
              name: 'EVALUATION_EVIDENCE_CONTAINER'
              value: 'evaluation-evidence'
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: configuration.applicationInsightsConnectionString
            }
            {
              name: 'APPLICATIONINSIGHTS_AUTHENTICATION_STRING'
              value: 'Authorization=AAD;ClientId=${identities.evaluationJob.clientId}'
            }
          ]
          resources: {
            cpu: json('2.0')
            memory: '4Gi'
          }
        }
      ]
    }
  }
}

resource foundryConfigurationJob 'Microsoft.App/jobs@2025-01-01' = if (deployFoundryConfiguration) {
  name: 'caj-foundry-config-${suffix}'
  location: location
  tags: union(tags, {
    'azd-service-name': 'foundry-configuration-job'
  })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identities.foundryConfigurator.id}': {}
    }
  }
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      replicaRetryLimit: 0
      replicaTimeout: 1800
      triggerType: 'Manual'
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: [
        {
          identity: identities.foundryConfigurator.id
          server: registry.loginServer
        }
      ]
      secrets: [
        {
          name: 'foundry-oauth-client-secret'
          keyVaultUrl: '${configuration.keyVaultUri}secrets/intake-foundry-oauth-client-secret'
          identity: identities.foundryConfigurator.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'foundry-configuration'
          image: foundryConfigurationImage
          env: [
            {
              name: 'AZURE_CLIENT_ID'
              value: identities.foundryConfigurator.clientId
            }
            {
              name: 'AZURE_TENANT_ID'
              value: configuration.entraTenantId
            }
            {
              name: 'FOUNDRY_PROJECT_ENDPOINT'
              value: configuration.foundryProjectEndpoint
            }
            {
              name: 'FOUNDRY_PROJECT_RESOURCE_ID'
              value: configuration.foundryProjectId
            }
            {
              name: 'FOUNDRY_OAUTH_CLIENT_ID'
              value: configuration.foundryOAuthClientId
            }
            {
              name: 'FOUNDRY_OAUTH_CLIENT_SECRET'
              secretRef: 'foundry-oauth-client-secret'
            }
            {
              name: 'INTAKE_REQUESTER_MCP_URL'
              value: 'https://${commandServiceName}.${environment.defaultDomain}/requester/mcp'
            }
            {
              name: 'INTAKE_REVIEWER_MCP_URL'
              value: 'https://${commandServiceName}.${environment.defaultDomain}/reviewer/mcp'
            }
            {
              name: 'MCP_AUDIENCE'
              value: configuration.mcpAudience
            }
            {
              name: 'MCP_REQUIRED_SCOPE'
              value: configuration.mcpRequiredScope
            }
            {
              name: 'AZURE_AI_MODEL_DEPLOYMENT_NAME'
              value: configuration.foundryModelDeployment
            }
            {
              name: 'HOSTED_AGENT_IMAGE'
              value: hostedAgentImage
            }
          ]
          resources: {
            cpu: json('2.0')
            memory: '4Gi'
          }
        }
      ]
    }
  }
}

output workloadResourceNames object = {
  commandService: deployWorkloads ? commandService.name : commandServiceName
  workers: {
    outbox: 'ca-outbox-${suffix}'
    notification: 'ca-notification-${suffix}'
    integration: 'ca-integration-${suffix}'
    completion: 'ca-completion-${suffix}'
    retention: 'ca-retention-${suffix}'
  }
  evaluationJob: deployEvaluation ? evaluationJob.name : 'caj-intake-evaluation-${suffix}'
  foundryConfigurationJob: deployFoundryConfiguration ? foundryConfigurationJob.name : 'caj-foundry-config-${suffix}'
}
