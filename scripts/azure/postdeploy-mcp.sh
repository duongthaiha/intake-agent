#!/usr/bin/env bash
# Verify the private MCP revision, then remove legacy runtime data permissions
# from the Hosted Agent identity. Idempotent and intentionally ordered so an
# unhealthy deployment never triggers the authorization cutover.
set -euo pipefail

for name in AZURE_SUBSCRIPTION_ID AZURE_RESOURCE_GROUP AZURE_MCP_CONTAINER_APP_NAME \
  MCP_RUNTIME_PRINCIPAL_ID AGENT_RUNTIME_PRINCIPAL_ID AZURE_STORAGE_ACCOUNT_NAME \
  AZURE_SERVICEBUS_NAMESPACE AZURE_COSMOS_ACCOUNT_NAME; do
  [[ -n "${!name:-}" ]] || { echo "$name is required" >&2; exit 1; }
done

az account set --subscription "$AZURE_SUBSCRIPTION_ID"
app_json="$(az containerapp show -g "$AZURE_RESOURCE_GROUP" -n "$AZURE_MCP_CONTAINER_APP_NAME" -o json)"
[[ "$(jq -r '.properties.provisioningState' <<<"$app_json")" == "Succeeded" ]] ||
  { echo "MCP Container App provisioning did not succeed" >&2; exit 1; }
latest="$(jq -r '.properties.latestRevisionName // empty' <<<"$app_json")"
ready="$(jq -r '.properties.latestReadyRevisionName // empty' <<<"$app_json")"
[[ -n "$latest" && "$latest" == "$ready" ]] ||
  { echo "MCP latest revision is not ready; Hosted Agent data access was not removed" >&2; exit 1; }
[[ "$(jq -r '.properties.configuration.ingress.external' <<<"$app_json")" == "false" ]] ||
  { echo "MCP ingress is public; refusing cutover" >&2; exit 1; }

base="/subscriptions/${AZURE_SUBSCRIPTION_ID}/resourceGroups/${AZURE_RESOURCE_GROUP}/providers"
storage_scope="${base}/Microsoft.Storage/storageAccounts/${AZURE_STORAGE_ACCOUNT_NAME}"
sb_short="${AZURE_SERVICEBUS_NAMESPACE%.servicebus.windows.net}"
sb_scope="${base}/Microsoft.ServiceBus/namespaces/${sb_short}"
cosmos_scope="${base}/Microsoft.DocumentDB/databaseAccounts/${AZURE_COSMOS_ACCOUNT_NAME}"

for spec in \
  "Storage Blob Data Contributor|${storage_scope}" \
  "Azure Service Bus Data Sender|${sb_scope}"; do
  IFS='|' read -r role scope <<<"$spec"
  count="$(az role assignment list --assignee-object-id "$MCP_RUNTIME_PRINCIPAL_ID" \
    --all --query "[?roleDefinitionName=='${role}' && scope=='${scope}'] | length(@)" -o tsv)"
  [[ "$count" -gt 0 ]] || { echo "MCP identity is missing $role; refusing cutover" >&2; exit 1; }
done
mcp_cosmos="$(az cosmosdb sql role assignment list -g "$AZURE_RESOURCE_GROUP" \
  -a "$AZURE_COSMOS_ACCOUNT_NAME" \
  --query "[?principalId=='${MCP_RUNTIME_PRINCIPAL_ID}'] | length(@)" -o tsv)"
[[ "$mcp_cosmos" -gt 0 ]] || { echo "MCP identity is missing Cosmos data access; refusing cutover" >&2; exit 1; }

if [[ "${MCP_DATA_PLANE_CUTOVER_APPROVED:-false}" != "true" ]]; then
echo "MCP revision is ready. Hosted Agent data-plane roles were retained."
echo "Complete delegated-user Toolbox verification, record approval, then rerun with MCP_DATA_PLANE_CUTOVER_APPROVED=true."
exit 0
fi

for spec in \
  "Storage Blob Data Contributor|${storage_scope}" \
  "Storage Blob Delegator|${storage_scope}" \
  "Azure Service Bus Data Sender|${sb_scope}"; do
  IFS='|' read -r role scope <<<"$spec"
  ids="$(az role assignment list --assignee-object-id "$AGENT_RUNTIME_PRINCIPAL_ID" \
    --all --query "[?roleDefinitionName=='${role}' && starts_with(scope, '${scope}')].id" \
    -o tsv 2>/dev/null || true)"
  for id in $ids; do
    az role assignment delete --ids "$id" --only-show-errors
    echo "removed Hosted Agent runtime role: $role"
  done
done

ids="$(az cosmosdb sql role assignment list -g "$AZURE_RESOURCE_GROUP" \
  -a "$AZURE_COSMOS_ACCOUNT_NAME" \
  --query "[?principalId=='${AGENT_RUNTIME_PRINCIPAL_ID}'].id" -o tsv 2>/dev/null || true)"
for id in $ids; do
  az cosmosdb sql role assignment delete -g "$AZURE_RESOURCE_GROUP" \
    -a "$AZURE_COSMOS_ACCOUNT_NAME" --role-assignment-id "${id##*/}" --yes --only-show-errors
  echo "removed Hosted Agent Cosmos data-plane assignment"
done
echo "MCP revision ready and Hosted Agent runtime data-plane cutover complete."
