#!/usr/bin/env bash
# Blocking verification after azd deploy. Run from the private ACA runner,
# from the azd project root (deploy.yml invokes it there).
#
# Foundry outputs are read from the OS environment when the caller exported
# them, and otherwise resolved from the azd environment — `azd provision`
# writes every Bicep output (AZURE_AI_PROJECT_ENDPOINT, AZURE_AI_ACCOUNT_NAME,
# …) there, but azd only injects them into hook processes, not into an
# ordinary workflow step. Resolving them here is what makes this script
# runnable at all; it previously aborted on the very first line.
set -euo pipefail

ENV_NAME="${AZURE_ENV_NAME:-dev}"
SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:-$(az account show --query id -o tsv)}"
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-rg-intake-${ENV_NAME}}"
PASS=0
FAIL=0

pass() { echo "  ✅ $*"; PASS=$((PASS + 1)); }
fail() { echo "  ❌ $*"; FAIL=$((FAIL + 1)); }
check() {
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then pass "$label"; else fail "$label"; fi
}
section() { echo; echo "━━━ $* ━━━"; }
private_ip() {
  [[ "$1" =~ ^10\. || "$1" =~ ^192\.168\. ||
     "$1" =~ ^172\.(1[6-9]|2[0-9]|3[0-1])\. ]]
}

# Read a single azd environment value without letting azd's own diagnostics
# leak into the result, and without aborting the script when the key is unset.
azd_env_value() {
  azd env get-value "$1" --environment "$ENV_NAME" --no-prompt 2>/dev/null |
    tr -d '\r' | grep -E '\S' | tail -n1 || true
}

section "Resolving deployment outputs"
PROJECT_ENDPOINT="${AZURE_AI_PROJECT_ENDPOINT:-}"
if [[ -z "$PROJECT_ENDPOINT" ]]; then
  PROJECT_ENDPOINT="$(azd_env_value AZURE_AI_PROJECT_ENDPOINT)"
fi
if [[ "$PROJECT_ENDPOINT" =~ ^https?:// ]]; then
  pass "Foundry project endpoint resolved"
else
  fail "AZURE_AI_PROJECT_ENDPOINT unavailable from the environment or 'azd env get-value'"
  PROJECT_ENDPOINT=""
fi

# Verify the Foundry account this deployment actually produced, rather than
# whichever Cognitive Services account happens to be listed first in the RG.
FOUNDRY_NAME="${AZURE_AI_ACCOUNT_NAME:-}"
if [[ -z "$FOUNDRY_NAME" ]]; then
  FOUNDRY_NAME="$(azd_env_value AZURE_AI_ACCOUNT_NAME)"
fi
if [[ "$FOUNDRY_NAME" =~ ^[A-Za-z0-9][A-Za-z0-9-]*$ ]]; then
  pass "Foundry account name resolved from azd outputs: $FOUNDRY_NAME"
else
  fail "AZURE_AI_ACCOUNT_NAME unavailable from the environment or 'azd env get-value'"
  FOUNDRY_NAME=""
fi

section "Foundation and data resources"
check "Resource group provisioned" test "$(az group show -n "$RESOURCE_GROUP" --subscription "$SUBSCRIPTION" --query properties.provisioningState -o tsv)" = Succeeded

COSMOS_NAME="$(az cosmosdb list -g "$RESOURCE_GROUP" --subscription "$SUBSCRIPTION" --query "[0].name" -o tsv 2>/dev/null || true)"
SB_NAME="$(az servicebus namespace list -g "$RESOURCE_GROUP" --subscription "$SUBSCRIPTION" --query "[0].name" -o tsv 2>/dev/null || true)"
SEARCH_NAME="$(az search service list -g "$RESOURCE_GROUP" --subscription "$SUBSCRIPTION" --query "[0].name" -o tsv 2>/dev/null || true)"
STORAGE_NAME="$(az storage account list -g "$RESOURCE_GROUP" --subscription "$SUBSCRIPTION" --query "[0].name" -o tsv 2>/dev/null || true)"
# `set -e` plus `[[ ... ]] && check ...` would abort the whole run (and skip
# the summary) the moment one resource is absent, so every conditional check
# below is written as an explicit if/else that records a failure and carries on.
for value in COSMOS_NAME SB_NAME SEARCH_NAME STORAGE_NAME; do
  if [[ -z "${!value}" ]]; then fail "Required data resource missing: $value"; fi
done
if [[ -n "$COSMOS_NAME" ]]; then
  check "Cosmos DB provisioned" test "$(az cosmosdb show -g "$RESOURCE_GROUP" -n "$COSMOS_NAME" --query provisioningState -o tsv)" = Succeeded
fi
if [[ -n "$SB_NAME" ]]; then
  check "Service Bus provisioned" test "$(az servicebus namespace show -g "$RESOURCE_GROUP" -n "$SB_NAME" --query provisioningState -o tsv)" = Succeeded
fi
if [[ -n "$SEARCH_NAME" ]]; then
  check "AI Search provisioned" test "$(az search service show -g "$RESOURCE_GROUP" -n "$SEARCH_NAME" --query provisioningState -o tsv)" = Succeeded
fi
if [[ -n "$STORAGE_NAME" ]]; then
  check "Storage provisioned" test "$(az storage account show -g "$RESOURCE_GROUP" -n "$STORAGE_NAME" --query provisioningState -o tsv)" = Succeeded
fi

for spec in 'request-state:/requestId' 'templates:/templateId' 'idempotency:/scopeId'; do
  IFS=: read -r container partition_key <<< "$spec"
  actual="$(az cosmosdb sql container show -g "$RESOURCE_GROUP" -a "$COSMOS_NAME" -d intake -n "$container" --query resource.partitionKey.paths[0] -o tsv 2>/dev/null || true)"
  if [[ "$actual" == "$partition_key" ]]; then
    pass "Cosmos container $container"
  else
    fail "Cosmos container $container partition key"
  fi
done

# `-o tsv` renders a multi-field projection as TAB-separated columns, so the
# previous single "Active:true:" comparison could never match. Status and
# duplicate detection are asserted as two independent scalar queries.
if [[ -n "$SB_NAME" ]]; then
  SB_QUEUE_STATUS="$(az servicebus queue show -g "$RESOURCE_GROUP" --namespace-name "$SB_NAME" -n domain-events-durable --query status -o tsv 2>/dev/null || true)"
  SB_QUEUE_DEDUPE="$(az servicebus queue show -g "$RESOURCE_GROUP" --namespace-name "$SB_NAME" -n domain-events-durable --query requiresDuplicateDetection -o tsv 2>/dev/null || true)"
  if [[ "$SB_QUEUE_STATUS" == "Active" ]]; then
    pass "Service Bus durable queue is Active"
  else
    fail "Service Bus durable queue status: ${SB_QUEUE_STATUS:-unavailable}"
  fi
  if [[ "$SB_QUEUE_DEDUPE" == "true" || "$SB_QUEUE_DEDUPE" == "True" ]]; then
    pass "Service Bus durable queue has duplicate detection enabled"
  else
    fail "Service Bus durable queue duplicate detection: ${SB_QUEUE_DEDUPE:-unavailable}"
  fi
else
  fail "Service Bus durable queue could not be checked: no namespace found"
fi

section "Application and identities"
check "Function App is Running" test "$(az functionapp show -g "$RESOURCE_GROUP" -n "func-intake-${ENV_NAME}" --query state -o tsv)" = Running
for identity in agent worker eval notify runner; do
  check "Managed identity id-intake-${identity}-${ENV_NAME}" \
    az identity show -g "$RESOURCE_GROUP" -n "id-intake-${identity}-${ENV_NAME}"
done

section "Runner bootstrap resources"
ACR_NAME="$(az acr list -g "$RESOURCE_GROUP" --subscription "$SUBSCRIPTION" --query "[?tags.'azd-env-name'=='${ENV_NAME}'].name | [0]" -o tsv 2>/dev/null || true)"
RUNNER_JOB="job-intake-runner-${ENV_NAME}"
if [[ -n "$ACR_NAME" ]]; then
  pass "Runner ACR present: $ACR_NAME"
  check "Runner ACR public access disabled" test "$(az acr show -g "$RESOURCE_GROUP" -n "$ACR_NAME" --query publicNetworkAccess -o tsv)" = Disabled
else
  fail "Runner ACR missing"
fi
check "Runner job present" az containerapp job show -g "$RESOURCE_GROUP" -n "$RUNNER_JOB"
check "Runner job event-triggered" test "$(az containerapp job show -g "$RESOURCE_GROUP" -n "$RUNNER_JOB" --query properties.configuration.triggerType -o tsv)" = Event

section "Hosted Agent and private path"
# Flags below are confirmed against microsoft.foundry (azd ai agent):
#   show   — [name], global -e/--environment, --no-prompt, -o/--output json|table
#   invoke — [name] [message], --new-session, -t/--timeout <seconds>, plus the
#            same global flags. The real remote invocation is intentionally
#            retained: it is the only check that proves the private data path
#            end to end.
SHOW_JSON="$(azd ai agent show intake-agent --environment "$ENV_NAME" --no-prompt --output json 2>/dev/null || true)"
if [[ -n "$SHOW_JSON" ]]; then pass "Hosted Agent show succeeded"; else fail "Hosted Agent show failed"; fi
if azd ai agent invoke intake-agent "Return exactly: health check passed." \
  --environment "$ENV_NAME" --new-session --timeout 120 --no-prompt >/dev/null; then
  pass "Hosted Agent private invocation succeeded"
else
  fail "Hosted Agent private invocation failed"
fi

if [[ -n "$PROJECT_ENDPOINT" ]]; then
  PROJECT_HOST="$(printf '%s' "$PROJECT_ENDPOINT" | sed -E 's#^https?://([^/]+).*$#\1#')"
  RESOLVED_IP="$(getent hosts "$PROJECT_HOST" 2>/dev/null | awk 'NR==1 {print $1}' || true)"
  if [[ -z "$RESOLVED_IP" ]]; then
    RESOLVED_IP="$(python3 -c 'import socket,sys; print(socket.gethostbyname(sys.argv[1]))' "$PROJECT_HOST" 2>/dev/null || true)"
  fi
  if private_ip "$RESOLVED_IP"; then
    pass "Foundry private DNS: $PROJECT_HOST -> $RESOLVED_IP"
  else
    fail "Foundry private DNS is not RFC1918: ${RESOLVED_IP:-no answer}"
  fi
  HTTP_CODE="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' --max-time 15 "https://${PROJECT_HOST}/" 2>/dev/null || true)"
  if [[ -n "$HTTP_CODE" && "$HTTP_CODE" != "000" ]]; then
    pass "Foundry private TLS responds (HTTP $HTTP_CODE)"
  else
    fail "Foundry private TLS did not respond"
  fi
fi

if [[ -n "$FOUNDRY_NAME" ]]; then
  check "Foundry public access disabled" test "$(az cognitiveservices account show -g "$RESOURCE_GROUP" -n "$FOUNDRY_NAME" --query properties.publicNetworkAccess -o tsv)" = Disabled
fi

echo; echo "━━━ Post-Deploy Verification Summary ━━━"; echo "  Passed: $PASS"; echo "  Failed: $FAIL"
[[ "$FAIL" -eq 0 ]]
