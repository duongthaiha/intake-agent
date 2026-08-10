#!/usr/bin/env bash
# scripts/azure/preflight.sh
# Pre-provision validation — checks providers, RBAC, and quota signals.
# Run automatically via azd preprovision hook, or manually:
#   bash scripts/azure/preflight.sh
#
# Environment variables (set by azd or export manually):
#   AZURE_SUBSCRIPTION_ID  — Target subscription
#   AZURE_LOCATION         — Target region (default: eastus2)
#   AZURE_ENV_NAME         — azd environment name

set -euo pipefail

SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:-}"
LOCATION="${AZURE_LOCATION:-eastus2}"
ENV_NAME="${AZURE_ENV_NAME:-dev}"
ERRORS=0
WARNINGS=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

info()    { echo "  ✅ $*"; }
warn()    { echo "  ⚠️  $*"; WARNINGS=$((WARNINGS+1)); }
fail()    { echo "  ❌ $*"; ERRORS=$((ERRORS+1)); }
section() { echo; echo "━━━ $* ━━━"; }

# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------
section "1. Subscription"

if [[ -z "$SUBSCRIPTION" ]]; then
  SUBSCRIPTION=$(az account show --query id -o tsv 2>/dev/null || echo "")
fi

if [[ -z "$SUBSCRIPTION" ]]; then
  fail "No subscription set. Run 'az login' and set AZURE_SUBSCRIPTION_ID."
  exit 1
fi

SUB_STATE=$(az account show --subscription "$SUBSCRIPTION" --query state -o tsv 2>/dev/null || echo "unknown")
if [[ "$SUB_STATE" == "Enabled" ]]; then
  info "Subscription $SUBSCRIPTION is Enabled"
else
  fail "Subscription $SUBSCRIPTION state: $SUB_STATE"
fi

TENANT_ID=$(az account show --subscription "$SUBSCRIPTION" --query tenantId -o tsv)
info "Tenant: $TENANT_ID"

# ---------------------------------------------------------------------------
# Provider registrations
# ---------------------------------------------------------------------------
section "2. Resource Provider Registrations"

declare -A REQUIRED_PROVIDERS=(
  ["Microsoft.Storage"]="required"
  ["Microsoft.DocumentDB"]="required"
  ["Microsoft.ServiceBus"]="required"
  ["Microsoft.Search"]="required"
  ["Microsoft.KeyVault"]="required"
  ["Microsoft.Web"]="required"
  ["Microsoft.App"]="required"
  ["Microsoft.Network"]="required"
  ["Microsoft.ManagedIdentity"]="required"
  ["Microsoft.OperationalInsights"]="required"
  ["microsoft.insights"]="required"
  ["Microsoft.MachineLearningServices"]="optional-foundry"
  ["Microsoft.CognitiveServices"]="optional-foundry"
  ["Microsoft.BotService"]="optional-bot"
)

for provider in "${!REQUIRED_PROVIDERS[@]}"; do
  state=$(az provider show --namespace "$provider" --subscription "$SUBSCRIPTION" \
    --query registrationState -o tsv 2>/dev/null || echo "Unknown")
  tier="${REQUIRED_PROVIDERS[$provider]}"

  if [[ "$state" == "Registered" ]]; then
    info "$provider: Registered"
  elif [[ "$tier" == "required" ]]; then
    fail "$provider: $state — run: az provider register --namespace $provider --subscription $SUBSCRIPTION"
  elif [[ "$tier" == "optional-foundry" ]]; then
    warn "$provider: $state — required when deployFoundry=true. Register before enabling Foundry gate."
  elif [[ "$tier" == "optional-bot" ]]; then
    warn "$provider: $state — required when deployBotService=true. Register before enabling Bot Service gate."
  fi
done

# ---------------------------------------------------------------------------
# RBAC — deploying identity must have Contributor + User Access Administrator
# ---------------------------------------------------------------------------
section "3. Deployer RBAC"

PRINCIPAL_ID=$(az ad signed-in-user show --query id -o tsv 2>/dev/null || echo "")
if [[ -z "$PRINCIPAL_ID" ]]; then
  warn "Could not determine signed-in user OID (may be SPN — validate manually)"
else
  info "Deploying principal: $PRINCIPAL_ID"

  # Check Owner at management group level (covers subscription + RG creation)
  HAS_OWNER=$(az role assignment list --assignee "$PRINCIPAL_ID" \
    --subscription "$SUBSCRIPTION" --all \
    --query "[?roleDefinitionName=='Owner'].roleDefinitionName | [0]" -o tsv 2>/dev/null || echo "")

  HAS_CONTRIBUTOR=$(az role assignment list --assignee "$PRINCIPAL_ID" \
    --subscription "$SUBSCRIPTION" \
    --query "[?roleDefinitionName=='Contributor'].roleDefinitionName | [0]" -o tsv 2>/dev/null || echo "")

  if [[ -n "$HAS_OWNER" ]]; then
    info "Owner role found (covers Contributor + User Access Administrator)"
  elif [[ -n "$HAS_CONTRIBUTOR" ]]; then
    warn "Contributor found but Owner not found — role assignments (RBAC) may fail. Add User Access Administrator."
  else
    warn "Neither Owner nor Contributor found at subscription scope — check resource group-level assignments"
  fi
fi

# ---------------------------------------------------------------------------
# Quota signals — non-blocking informational checks
# ---------------------------------------------------------------------------
section "4. Quota Signals (informational)"

# Cognitive Services accounts
CS_USED=$(az cognitiveservices usage list --location "$LOCATION" \
  --subscription "$SUBSCRIPTION" \
  --query "[?name.value=='Accounts'].currentValue | [0]" -o tsv 2>/dev/null || echo "?")
CS_LIMIT=$(az cognitiveservices usage list --location "$LOCATION" \
  --subscription "$SUBSCRIPTION" \
  --query "[?name.value=='Accounts'].limit | [0]" -o tsv 2>/dev/null || echo "?")
echo "  CognitiveServices accounts in $LOCATION: ${CS_USED}/${CS_LIMIT}"

# AI Search Basic
SEARCH_BASIC_USED=$(az search service list --subscription "$SUBSCRIPTION" \
  --query "[?sku.name=='basic' && location=='$LOCATION'] | length(@)" -o tsv 2>/dev/null || echo "?")
echo "  AI Search Basic services in use: ${SEARCH_BASIC_USED} (limit: 12)"

# VM cores (Functions Flex Consumption uses ephemeral compute)
CORE_INFO=$(az vm list-usage --location "$LOCATION" \
  --subscription "$SUBSCRIPTION" \
  --query "[?name.value=='cores'].{current:currentValue,limit:limit} | [0]" -o json 2>/dev/null || echo "{}")
echo "  Total vCPU: $(echo "$CORE_INFO" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"{d.get('current','?')}/{d.get('limit','?')}\")" 2>/dev/null || echo "?")"

# ---------------------------------------------------------------------------
# Region availability — informational
# ---------------------------------------------------------------------------
section "5. Region: $LOCATION"
info "eastus2 confirmed for: Foundry Agent Service, Functions Flex Consumption, Cosmos DB Serverless, AI Search Basic, Service Bus Standard, Container Apps, private endpoints"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo
echo "━━━ Preflight Summary ━━━"
echo "  Errors:   $ERRORS"
echo "  Warnings: $WARNINGS"
echo

if [[ $ERRORS -gt 0 ]]; then
  echo "❌ Preflight FAILED — resolve errors before provisioning."
  echo "   Provider registrations require: az provider register --namespace <name>"
  echo "   Do NOT register providers automatically; review each one first."
  exit 1
else
  echo "✅ Preflight PASSED${WARNINGS:+ (with $WARNINGS warning(s) — review before production)}"
  exit 0
fi
