@description('Microsoft Foundry account name.')
param accountName string

@description('Microsoft Foundry project name.')
param projectName string

@description('Connection names configured on the project.')
param connectionNames object

resource account 'Microsoft.CognitiveServices/accounts@2026-05-01' existing = {
  name: accountName
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2026-05-01' existing = {
  parent: account
  name: projectName
}

resource capabilityHost 'Microsoft.CognitiveServices/accounts/projects/capabilityHosts@2026-05-01' = {
  parent: project
  name: 'agents'
  properties: {
    // The ARM API requires this documented property while the generated Bicep type lags the API.
    #disable-next-line BCP037
    capabilityHostKind: 'Agents'
    storageConnections: [
      connectionNames.storage
    ]
    threadStorageConnections: [
      connectionNames.cosmos
    ]
    vectorStoreConnections: [
      connectionNames.search
    ]
  }
}

output capabilityHostId string = capabilityHost.id
