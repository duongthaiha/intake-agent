@description('Deploy runtime resource placeholders only after immutable images are available.')
param deployWorkloads bool = false

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

resource commandService 'Microsoft.App/containerApps@2026-01-01' = if (deployWorkloads) {
  name: 'ca-intake-command-${suffix}'
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
              value: configuration.serviceBusNamespace
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
  for worker in workerDefinitions: if (deployWorkloads) {
    name: 'ca-intake-${worker.name}-${suffix}'
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
                value: configuration.serviceBusNamespace
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

resource evaluationJob 'Microsoft.App/jobs@2025-01-01' = if (deployWorkloads) {
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
      replicaRetryLimit: 1
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
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: configuration.applicationInsightsConnectionString
            }
            {
              name: 'APPLICATIONINSIGHTS_AUTHENTICATION_STRING'
              value: 'Authorization=AAD;ClientId=${identities.evaluationJob.clientId}'
            }
          ]
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
        }
      ]
    }
  }
}

output workloadResourceNames object = {
  commandService: deployWorkloads ? commandService.name : 'ca-intake-command-${suffix}'
  workers: {
    outbox: 'ca-intake-outbox-${suffix}'
    notification: 'ca-intake-notification-${suffix}'
    integration: 'ca-intake-integration-${suffix}'
    completion: 'ca-intake-completion-${suffix}'
    retention: 'ca-intake-retention-${suffix}'
  }
  evaluationJob: deployWorkloads ? evaluationJob.name : 'caj-intake-evaluation-${suffix}'
}
