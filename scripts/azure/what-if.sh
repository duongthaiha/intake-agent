#!/usr/bin/env bash
# scripts/azure/what-if.sh
# Run ARM what-if for the intake-agent Bicep deployment.
# Shows what resources will be created/modified/deleted without deploying.
#
# Usage:
#   bash scripts/azure/what-if.sh [env-name] [location]
#   AZURE_SUBSCRIPTION_ID=<id> bash scripts/azure/what-if.sh dev eastus2

set -euo pipefail

ENV_NAME="${1:-${AZURE_ENV_NAME:-dev}}"
LOCATION="${2:-${AZURE_LOCATION:-eastus2}}"
SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:-}"
RG_NAME="rg-intake-${ENV_NAME}"

if [[ -z "$SUBSCRIPTION" ]]; then
  SUBSCRIPTION=$(az account show --query id -o tsv 2>/dev/null || echo "")
fi

if [[ -z "$SUBSCRIPTION" ]]; then
  echo "❌ AZURE_SUBSCRIPTION_ID not set and no default account. Run 'az login' first."
  exit 1
fi

echo "━━━ Bicep What-If ━━━"
echo "  Environment:  $ENV_NAME"
echo "  Location:     $LOCATION"
echo "  Subscription: $SUBSCRIPTION"
echo "  Resource Group (target): $RG_NAME"
echo

# Get deploying principal ID (best effort)
PRINCIPAL_ID=$(az ad signed-in-user show --query id -o tsv 2>/dev/null || echo "")

az deployment sub what-if \
  --subscription "$SUBSCRIPTION" \
  --location "$LOCATION" \
  --template-file infra/main.bicep \
  --parameters infra/main.parameters.json \
  --parameters environmentName="$ENV_NAME" \
               location="$LOCATION" \
               principalId="$PRINCIPAL_ID" \
               deployFoundry=false \
               deployBotService=false \
               deployPrivateEndpoints=false \
  --result-format FullResourcePayloads \
  --exclude-change-types Ignore Unsupported NoChange 2>&1

echo
echo "✅ What-if complete. Review changes above before running 'azd provision'."
