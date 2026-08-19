#!/usr/bin/env bash
# scripts/azure/ensure-hosted-agent-rbac.sh
# POSIX port of ensure-hosted-agent-rbac.ps1 — narrow, data-plane-scoped RBAC
# reconciliation for the Hosted Agent runtime identity (agent UAMI). Wired
# into azure.yaml's postprovision hook (scripts/azure/postprovision.sh) so it
# runs automatically after every `azd provision`, on both Windows and POSIX
# runners, instead of being an orphaned script that nobody calls.
#
# Idempotent: only creates a role assignment if an identical one is not
# already present. Safe to re-run on every deploy.
#
# Required environment variables (all populated by azd from Bicep outputs —
# see infra/main.bicep):
#   AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP, AGENT_RUNTIME_PRINCIPAL_ID,
#   AZURE_COSMOS_ACCOUNT_NAME, AZURE_COSMOS_DATABASE, AZURE_STORAGE_ACCOUNT_NAME,
#   AZURE_STORAGE_ARTIFACTS_CONTAINER, AZURE_SERVICEBUS_NAMESPACE,
#   AZURE_SERVICEBUS_QUEUE, AZURE_SEARCH_SERVICE_NAME, AZURE_AI_ACCOUNT_NAME
#
# Optional: PRUNE_LEGACY_BROAD_ASSIGNMENTS=true to remove broad
# account/namespace-scoped role assignments once narrow ones are confirmed.

set -euo pipefail

: "${AZURE_SUBSCRIPTION_ID:?AZURE_SUBSCRIPTION_ID is required}"
: "${AZURE_RESOURCE_GROUP:?AZURE_RESOURCE_GROUP is required}"
: "${AGENT_RUNTIME_PRINCIPAL_ID:?AGENT_RUNTIME_PRINCIPAL_ID is required}"
: "${AZURE_COSMOS_ACCOUNT_NAME:?AZURE_COSMOS_ACCOUNT_NAME is required}"
: "${AZURE_COSMOS_DATABASE:?AZURE_COSMOS_DATABASE is required}"
: "${AZURE_STORAGE_ACCOUNT_NAME:?AZURE_STORAGE_ACCOUNT_NAME is required}"
: "${AZURE_STORAGE_ARTIFACTS_CONTAINER:?AZURE_STORAGE_ARTIFACTS_CONTAINER is required}"
: "${AZURE_SERVICEBUS_NAMESPACE:?AZURE_SERVICEBUS_NAMESPACE is required}"
: "${AZURE_SERVICEBUS_QUEUE:?AZURE_SERVICEBUS_QUEUE is required}"
: "${AZURE_SEARCH_SERVICE_NAME:?AZURE_SEARCH_SERVICE_NAME is required}"
: "${AZURE_AI_ACCOUNT_NAME:?AZURE_AI_ACCOUNT_NAME is required}"

PRUNE_LEGACY_BROAD_ASSIGNMENTS="${PRUNE_LEGACY_BROAD_ASSIGNMENTS:-false}"

az account set --subscription "$AZURE_SUBSCRIPTION_ID"

SB_NAMESPACE_SHORT="${AZURE_SERVICEBUS_NAMESPACE%.servicebus.windows.net}"

BASE="/subscriptions/${AZURE_SUBSCRIPTION_ID}/resourceGroups/${AZURE_RESOURCE_GROUP}/providers"
STORAGE_SCOPE="${BASE}/Microsoft.Storage/storageAccounts/${AZURE_STORAGE_ACCOUNT_NAME}"
CONTAINER_SCOPE="${STORAGE_SCOPE}/blobServices/default/containers/${AZURE_STORAGE_ARTIFACTS_CONTAINER}"
SERVICEBUS_SCOPE="${BASE}/Microsoft.ServiceBus/namespaces/${SB_NAMESPACE_SHORT}"
QUEUE_SCOPE="${SERVICEBUS_SCOPE}/queues/${AZURE_SERVICEBUS_QUEUE}"
SEARCH_SCOPE="${BASE}/Microsoft.Search/searchServices/${AZURE_SEARCH_SERVICE_NAME}"
FOUNDRY_SCOPE="${BASE}/Microsoft.CognitiveServices/accounts/${AZURE_AI_ACCOUNT_NAME}"
COSMOS_SCOPE="${BASE}/Microsoft.DocumentDB/databaseAccounts/${AZURE_COSMOS_ACCOUNT_NAME}"
COSMOS_DATABASE_SCOPE="${COSMOS_SCOPE}/dbs/${AZURE_COSMOS_DATABASE}"
COSMOS_CONTRIBUTOR_ROLE="${COSMOS_SCOPE}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"

ensure_role() {
  local role="$1" scope="$2"
  local existing
  existing=$(az role assignment list \
    --assignee-object-id "$AGENT_RUNTIME_PRINCIPAL_ID" \
    --scope "$scope" \
    --query "[?roleDefinitionName=='${role}' && scope=='${scope}'].id | [0]" \
    -o tsv 2>/dev/null || echo "")
  if [[ -n "$existing" ]]; then
    echo "present: $role at $scope"
    return
  fi
  az role assignment create \
    --assignee-object-id "$AGENT_RUNTIME_PRINCIPAL_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "$role" \
    --scope "$scope" \
    --only-show-errors >/dev/null
  echo "created: $role at $scope"
}

ensure_role "Storage Blob Data Contributor" "$CONTAINER_SCOPE"
ensure_role "Storage Blob Delegator" "$STORAGE_SCOPE"
ensure_role "Azure Service Bus Data Sender" "$QUEUE_SCOPE"
ensure_role "Search Index Data Reader" "$SEARCH_SCOPE"
ensure_role "Cognitive Services User" "$FOUNDRY_SCOPE"

COSMOS_ASSIGNMENT=$(az cosmosdb sql role assignment list \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --account-name "$AZURE_COSMOS_ACCOUNT_NAME" \
  --query "[?principalId=='${AGENT_RUNTIME_PRINCIPAL_ID}' && scope=='${COSMOS_DATABASE_SCOPE}' && roleDefinitionId=='${COSMOS_CONTRIBUTOR_ROLE}'].id | [0]" \
  -o tsv 2>/dev/null || echo "")
if [[ -z "$COSMOS_ASSIGNMENT" ]]; then
  az cosmosdb sql role assignment create \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --account-name "$AZURE_COSMOS_ACCOUNT_NAME" \
    --principal-id "$AGENT_RUNTIME_PRINCIPAL_ID" \
    --role-definition-id "$COSMOS_CONTRIBUTOR_ROLE" \
    --scope "$COSMOS_DATABASE_SCOPE" \
    --only-show-errors >/dev/null
  echo "created: Cosmos DB Built-in Data Contributor at $COSMOS_DATABASE_SCOPE"
else
  echo "present: Cosmos DB Built-in Data Contributor at $COSMOS_DATABASE_SCOPE"
fi

if [[ "$PRUNE_LEGACY_BROAD_ASSIGNMENTS" == "true" ]]; then
  for pair in "Storage Blob Data Contributor|${STORAGE_SCOPE}" "Azure Service Bus Data Sender|${SERVICEBUS_SCOPE}"; do
    IFS='|' read -r legacy_role legacy_scope <<< "$pair"
    ids=$(az role assignment list \
      --assignee-object-id "$AGENT_RUNTIME_PRINCIPAL_ID" \
      --scope "$legacy_scope" \
      --query "[?roleDefinitionName=='${legacy_role}' && scope=='${legacy_scope}'].id" \
      -o tsv 2>/dev/null || echo "")
    for id in $ids; do
      az role assignment delete --ids "$id" --only-show-errors
      echo "removed legacy broad assignment: $legacy_role at $legacy_scope"
    done
  done

  legacy_cosmos_ids=$(az cosmosdb sql role assignment list \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --account-name "$AZURE_COSMOS_ACCOUNT_NAME" \
    --query "[?principalId=='${AGENT_RUNTIME_PRINCIPAL_ID}' && scope=='${COSMOS_SCOPE}' && roleDefinitionId=='${COSMOS_CONTRIBUTOR_ROLE}'].id" \
    -o tsv 2>/dev/null || echo "")
  for id in $legacy_cosmos_ids; do
    assignment_id="${id##*/}"
    az cosmosdb sql role assignment delete \
      --resource-group "$AZURE_RESOURCE_GROUP" \
      --account-name "$AZURE_COSMOS_ACCOUNT_NAME" \
      --role-assignment-id "$assignment_id" \
      --yes \
      --only-show-errors
    echo "removed legacy broad Cosmos assignment at $COSMOS_SCOPE"
  done
fi
