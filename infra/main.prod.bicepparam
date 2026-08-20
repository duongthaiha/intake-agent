using './main.bicep'

param environmentName = 'prod'
param location = 'eastus2'
param networkMode = 'hardened'
param owner = 'intake-agent-team'
param costCenter = 'unassigned'
param deployWorkloads = false
param cosmosMaxThroughput = 10000
param monthlyBudgetAmount = 5000
param budgetStartDate = '2026-08-01'
