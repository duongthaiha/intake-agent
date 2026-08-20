@description('Azure region for the workload route table.')
param location string

@description('Short, globally consistent resource-name suffix.')
param suffix string

@description('Common resource tags.')
param tags object

resource workloadRouteTable 'Microsoft.Network/routeTables@2024-07-01' = {
  name: 'rt-intake-egress-${suffix}'
  location: location
  tags: tags
  properties: {
    disableBgpRoutePropagation: false
    routes: []
  }
}

output routeTableId string = workloadRouteTable.id
output routeTableName string = workloadRouteTable.name
