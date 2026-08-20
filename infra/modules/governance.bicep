@description('Common resource tags.')
param tags object

@minValue(1)
@description('Monthly resource-group budget in the billing currency.')
param monthlyBudgetAmount int

@description('First day of the month from which the budget applies.')
param budgetStartDate string

@description('Apply a CanNotDelete lock to the resource group.')
param enableDeleteLock bool = false

@description('Optional built-in or custom Azure Policy definition resource IDs to assign at resource-group scope.')
param policyDefinitionIds array = []

resource budget 'Microsoft.Consumption/budgets@2024-08-01' = {
  name: 'monthly-intake-budget'
  properties: {
    amount: monthlyBudgetAmount
    category: 'Cost'
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: budgetStartDate
    }
    notifications: {
      Actual_GreaterThan_80_Percent: {
        contactEmails: []
        contactGroups: []
        contactRoles: [
          'Owner'
        ]
        enabled: true
        locale: 'en-us'
        operator: 'GreaterThan'
        threshold: 80
        thresholdType: 'Actual'
      }
      Forecasted_GreaterThan_100_Percent: {
        contactEmails: []
        contactGroups: []
        contactRoles: [
          'Owner'
        ]
        enabled: true
        locale: 'en-us'
        operator: 'GreaterThan'
        threshold: 100
        thresholdType: 'Forecasted'
      }
    }
  }
}

resource deleteLock 'Microsoft.Authorization/locks@2020-05-01' = if (enableDeleteLock) {
  name: 'protect-intake-foundation'
  properties: {
    level: 'CanNotDelete'
    notes: 'Prevents accidental deletion of the Intake Agent environment.'
  }
}

resource policyAssignments 'Microsoft.Authorization/policyAssignments@2025-03-01' = [
  for (policyDefinitionId, index) in policyDefinitionIds: {
    name: 'intake-policy-${index}'
    properties: {
      description: 'Governed Intake Agent policy assignment.'
      displayName: 'Intake Agent policy ${index}'
      enforcementMode: 'Default'
      metadata: {
        assignedBy: 'Intake Agent Bicep'
        tags: tags
      }
      policyDefinitionId: policyDefinitionId
    }
  }
]
