using './main.bicep'

param environmentName = 'test'
param location = 'eastus2'
param networkMode = 'hardened'
param owner = 'intake-agent-team'
param costCenter = 'unassigned'
param deployWorkloads = false
param cosmosMaxThroughput = 4000
param monthlyBudgetAmount = 1000
param budgetStartDate = '2026-08-01'
