using './main.bicep'

param environmentName = 'dev'
param location = 'eastus2'
param searchLocation = 'eastus'
param networkMode = 'hardened'
param owner = 'intake-agent-team'
param costCenter = 'unassigned'
param deployWorkloads = false
param cosmosMaxThroughput = 4000
param monthlyBudgetAmount = 500
param budgetStartDate = '2026-08-01'
