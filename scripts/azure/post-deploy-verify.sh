#!/usr/bin/env bash
# scripts/azure/post-deploy-verify.sh
# Post-provisioning smoke tests — validates that key resources are reachable
# and configured correctly after 'azd provision'.
#
# Usage:
#   bash scripts/azure/post-deploy-verify.sh
#   Environment variables: AZURE_ENV_NAME, AZURE_SUBSCRIPTION_ID

set -euo pipefail

ENV_NAME="${AZURE_ENV_NAME:-dev}"
SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:-}"
RG_NAME="rg-intake-${ENV_NAME}"
PASS=0
FAIL=0

if [[ -z "$SUBSCRIPTION" ]]; then
  SUBSCRIPTION=$(az account show --query id -o tsv 2>/dev/null || echo "")
fi

check_pass() { echo "  ✅ $*"; PASS=$((PASS+1)); }
check_fail() { echo "  ❌ $*"; FAIL=$((FAIL+1)); }
section()    { echo; echo "━━━ $* ━━━"; }

section "Resource Group"
RG_STATE=$(az group show --name "$RG_NAME" --subscription "$SUBSCRIPTION" \
  --query properties.provisioningState -o tsv 2>/dev/null || echo "NotFound")
if [[ "$RG_STATE" == "Succeeded" ]]; then
  check_pass "Resource group $RG_NAME: Succeeded"
else
  check_fail "Resource group $RG_NAME: $RG_STATE"
fi

section "Monitoring"
LOG_NAME=$(az monitor log-analytics workspace list --resource-group "$RG_NAME" \
  --subscription "$SUBSCRIPTION" --query "[0].name" -o tsv 2>/dev/null || echo "")
if [[ -n "$LOG_NAME" ]]; then
  check_pass "Log Analytics workspace: $LOG_NAME"
else
  check_fail "Log Analytics workspace not found in $RG_NAME"
fi

APPI_NAME=$(az monitor app-insights component show --query "[0].name" \
  --app "appi-intake-${ENV_NAME}" --resource-group "$RG_NAME" \
  --subscription "$SUBSCRIPTION" -o tsv 2>/dev/null || echo "")
if [[ -n "$APPI_NAME" ]]; then
  check_pass "Application Insights: $APPI_NAME"
else
  check_fail "Application Insights not found"
fi

section "Data Services"
COSMOS_NAME=$(az cosmosdb list --resource-group "$RG_NAME" --subscription "$SUBSCRIPTION" \
  --query "[0].name" -o tsv 2>/dev/null || echo "")
SB_NAME=$(az servicebus namespace list --resource-group "$RG_NAME" --subscription "$SUBSCRIPTION" \
  --query "[0].name" -o tsv 2>/dev/null || echo "")
SEARCH_NAME=$(az search service list --resource-group "$RG_NAME" --subscription "$SUBSCRIPTION" \
  --query "[0].name" -o tsv 2>/dev/null || echo "")

for resource_check in \
  "Cosmos DB:Microsoft.DocumentDB/databaseAccounts:${COSMOS_NAME}" \
  "Service Bus:Microsoft.ServiceBus/namespaces:${SB_NAME}" \
  "AI Search:Microsoft.Search/searchServices:${SEARCH_NAME}"; do
  IFS=: read -r LABEL TYPE NAME <<< "$resource_check"
  STATE=$(az resource show --ids \
    "/subscriptions/${SUBSCRIPTION}/resourceGroups/${RG_NAME}/providers/${TYPE}/${NAME}" \
    --query properties.provisioningState -o tsv 2>/dev/null || echo "NotFound")
  if [[ "$STATE" == "Succeeded" ]]; then
    check_pass "$LABEL: $NAME ($STATE)"
  else
    check_fail "$LABEL: $NAME ($STATE)"
  fi
done

for container_check in \
  "request-state:/requestId" \
  "templates:/templateId" \
  "idempotency:/scopeId"; do
  IFS=: read -r CONTAINER EXPECTED_PK <<< "$container_check"
  ACTUAL_PK=$(az cosmosdb sql container show \
    --resource-group "$RG_NAME" \
    --account-name "$COSMOS_NAME" \
    --database-name intake \
    --name "$CONTAINER" \
    --query "resource.partitionKey.paths[0]" -o tsv 2>/dev/null || echo "")
  if [[ "$ACTUAL_PK" == "$EXPECTED_PK" ]]; then
    check_pass "Cosmos container $CONTAINER: $ACTUAL_PK"
  else
    check_fail "Cosmos container $CONTAINER: expected $EXPECTED_PK, got $ACTUAL_PK"
  fi
done

DURABLE_QUEUE=$(az servicebus queue show \
  --resource-group "$RG_NAME" \
  --namespace-name "$SB_NAME" \
  --name domain-events-durable \
  --query "[name, requiresDuplicateDetection, status]" -o tsv 2>/dev/null || echo "")
if [[ "$DURABLE_QUEUE" == $'domain-events-durable\ttrue\tActive' ]]; then
  check_pass "Service Bus durable outbox queue: active with duplicate detection"
else
  check_fail "Service Bus durable outbox queue is missing or misconfigured"
fi

section "Managed Identities"
for mi in "agent" "worker" "eval" "notify"; do
  MI_NAME="id-intake-${mi}-${ENV_NAME}"
  MI_EXISTS=$(az identity show --name "$MI_NAME" --resource-group "$RG_NAME" \
    --subscription "$SUBSCRIPTION" --query name -o tsv 2>/dev/null || echo "")
  if [[ -n "$MI_EXISTS" ]]; then
    check_pass "Managed identity: $MI_NAME"
  else
    check_fail "Managed identity not found: $MI_NAME"
  fi
done

section "Azure Functions"
FUNC_NAME="func-intake-${ENV_NAME}"
FUNC_STATE=$(az resource show --ids \
  "/subscriptions/${SUBSCRIPTION}/resourceGroups/${RG_NAME}/providers/Microsoft.Web/sites/${FUNC_NAME}" \
  --api-version 2023-12-01 --query properties.state -o tsv 2>/dev/null || echo "NotFound")
if [[ "$FUNC_STATE" == "Running" ]]; then
  check_pass "Functions App: $FUNC_NAME ($FUNC_STATE)"
elif [[ "$FUNC_STATE" == "NotFound" ]]; then
  check_fail "Functions App not found: $FUNC_NAME"
else
  check_pass "Functions App: $FUNC_NAME (state: $FUNC_STATE)"
fi

section "Container Apps Environment"
CAE_NAME="cae-intake-${ENV_NAME}"
CAE_STATE=$(az containerapp env show --name "$CAE_NAME" --resource-group "$RG_NAME" \
  --subscription "$SUBSCRIPTION" --query properties.provisioningState -o tsv 2>/dev/null || echo "NotFound")
if [[ "$CAE_STATE" == "Succeeded" ]]; then
  check_pass "Container Apps Environment: $CAE_NAME"
else
  check_fail "Container Apps Environment: $CAE_NAME ($CAE_STATE)"
fi

section "VNet"
VNET_NAME="vnet-intake-${ENV_NAME}"
VNET_STATE=$(az network vnet show --name "$VNET_NAME" --resource-group "$RG_NAME" \
  --subscription "$SUBSCRIPTION" --query provisioningState -o tsv 2>/dev/null || echo "NotFound")
if [[ "$VNET_STATE" == "Succeeded" ]]; then
  check_pass "VNet: $VNET_NAME"
else
  check_fail "VNet: $VNET_NAME ($VNET_STATE)"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo
echo "━━━ Post-Deploy Verification Summary ━━━"
echo "  Passed: $PASS"
echo "  Failed: $FAIL"
echo

if [[ $FAIL -gt 0 ]]; then
  echo "⚠️  Some checks failed. Review output above."
  exit 1
else
  echo "✅ All checks passed."
  exit 0
fi
