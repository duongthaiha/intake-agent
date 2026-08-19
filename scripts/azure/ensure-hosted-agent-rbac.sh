#!/usr/bin/env bash
# Reconcile only the Hosted Agent's platform/tooling permissions.
# Runtime Cosmos, Blob, and Service Bus access belongs exclusively to the MCP
# identity and is removed by postdeploy-mcp.sh after the MCP revision is ready.
set -euo pipefail

: "${AZURE_SUBSCRIPTION_ID:?AZURE_SUBSCRIPTION_ID is required}"
: "${AZURE_RESOURCE_GROUP:?AZURE_RESOURCE_GROUP is required}"
: "${AGENT_RUNTIME_PRINCIPAL_ID:?AGENT_RUNTIME_PRINCIPAL_ID is required}"
: "${AZURE_SEARCH_SERVICE_NAME:?AZURE_SEARCH_SERVICE_NAME is required}"
: "${AZURE_AI_ACCOUNT_NAME:?AZURE_AI_ACCOUNT_NAME is required}"

az account set --subscription "$AZURE_SUBSCRIPTION_ID"
BASE="/subscriptions/${AZURE_SUBSCRIPTION_ID}/resourceGroups/${AZURE_RESOURCE_GROUP}/providers"

ensure_role() {
  local role="$1" scope="$2"
  if az role assignment list --assignee-object-id "$AGENT_RUNTIME_PRINCIPAL_ID" \
    --scope "$scope" --query "[?roleDefinitionName=='${role}' && scope=='${scope}'] | length(@)" \
    -o tsv 2>/dev/null | grep -qx '[1-9][0-9]*'; then
    echo "present: $role"
    return
  fi
  az role assignment create --assignee-object-id "$AGENT_RUNTIME_PRINCIPAL_ID" \
    --assignee-principal-type ServicePrincipal --role "$role" --scope "$scope" \
    --only-show-errors >/dev/null
  echo "created: $role"
}

ensure_role "Search Index Data Reader" \
  "${BASE}/Microsoft.Search/searchServices/${AZURE_SEARCH_SERVICE_NAME}"
ensure_role "Cognitive Services User" \
  "${BASE}/Microsoft.CognitiveServices/accounts/${AZURE_AI_ACCOUNT_NAME}"
