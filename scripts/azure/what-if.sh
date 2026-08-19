#!/usr/bin/env bash
# scripts/azure/what-if.sh
# Run ARM what-if for the intake-agent Bicep deployment.
# Shows what resources will be created/modified/deleted without deploying.
#
# IMPORTANT: parameter values passed here MUST match what `azd provision`
# will actually use (infra/main.parameters.json), otherwise what-if
# misrepresents the real deployment (this previously hardcoded
# deployFoundry=false/deployPrivateEndpoints=false while the real deploy
# used true/true — the drift this script now avoids). Private endpoints are
# no longer a parameter at all: main.bicep is private-only, and passing the
# removed deployPrivateEndpoints/deployStoragePrivateEndpoint flags here
# would now fail ARM validation outright.
#
# Usage:
#   bash scripts/azure/what-if.sh [env-name] [location]
#   AZURE_SUBSCRIPTION_ID=<id> AZURE_PRINCIPAL_ID=<service-principal-object-id> \
#     bash scripts/azure/what-if.sh dev eastus2
#
# Output is also written to what-if-<env-name>.json in the current directory
# so CI can attach it as a build artifact (evidence of the exact planned
# change set reviewed before `azd provision`).

set -euo pipefail

ENV_NAME="${1:-${AZURE_ENV_NAME:-dev}}"
LOCATION="${2:-${AZURE_LOCATION:-eastus2}}"
SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:-}"
RG_NAME="${AZURE_RESOURCE_GROUP:-rg-intake-${ENV_NAME}}"
EVIDENCE_FILE="what-if-${ENV_NAME}.json"

if [[ -z "$SUBSCRIPTION" ]]; then
  SUBSCRIPTION=$(az account show --query id -o tsv 2>/dev/null || echo "")
fi

if [[ -z "$SUBSCRIPTION" ]]; then
  echo "❌ AZURE_SUBSCRIPTION_ID not set and no default account. Run 'az login' first."
  exit 1
fi

: "${AZURE_PRINCIPAL_ID:?AZURE_PRINCIPAL_ID is required (federated service principal object ID)}"
: "${INTAKE_MCP_APP_CLIENT_ID:?INTAKE_MCP_APP_CLIENT_ID is required}"
: "${INTAKE_MCP_IMAGE:?INTAKE_MCP_IMAGE is required}"

echo "━━━ Bicep What-If ━━━"
echo "  Environment:  $ENV_NAME"
echo "  Location:     $LOCATION"
echo "  Subscription: $SUBSCRIPTION"
echo "  Resource Group (target): $RG_NAME"
echo

# Parameters below intentionally mirror infra/main.parameters.json's real
# values (not a divergent "safe" subset) so what-if reflects the actual
# provision, per-flag-for-flag.
trap 'rm -f "$EVIDENCE_FILE"' ERR
az deployment group what-if \
  --subscription "$SUBSCRIPTION" \
  --resource-group "$RG_NAME" \
  --template-file infra/main.bicep \
  --parameters infra/main.parameters.json \
  --parameters environmentName="$ENV_NAME" \
               location="$LOCATION" \
               principalId="$AZURE_PRINCIPAL_ID" \
               intakeMcpAppClientId="$INTAKE_MCP_APP_CLIENT_ID" \
               intakeMcpImage="$INTAKE_MCP_IMAGE" \
               deployBotService=false \
  --result-format FullResourcePayloads \
  --exclude-change-types Ignore Unsupported NoChange \
  | tee "$EVIDENCE_FILE"
trap - ERR

echo
echo "✅ What-if complete. Evidence captured: $EVIDENCE_FILE"
echo "   Review changes above before running 'azd provision'."
