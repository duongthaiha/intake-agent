#!/usr/bin/env bash
set -euo pipefail

: "${AZURE_RESOURCE_GROUP:?AZURE_RESOURCE_GROUP is required}"
: "${AZURE_COMMAND_SERVICE_NAME:?AZURE_COMMAND_SERVICE_NAME is required}"

command_fqdn="$(
  az containerapp show \
    --name "$AZURE_COMMAND_SERVICE_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn \
    --output tsv
)"
test -n "$command_fqdn"
curl \
  --fail \
  --retry 5 \
  --retry-all-errors \
  --retry-delay 5 \
  --silent \
  --show-error \
  "https://${command_fqdn}/healthz"

worker_variables=(
  AZURE_OUTBOX_WORKER_NAME
  AZURE_NOTIFICATION_WORKER_NAME
  AZURE_INTEGRATION_WORKER_NAME
  AZURE_COMPLETION_WORKER_NAME
  AZURE_RETENTION_WORKER_NAME
)

for variable in "${worker_variables[@]}"; do
  name="${!variable:-}"
  if [[ -z "$name" ]]; then
    echo "::error::$variable is required"
    exit 1
  fi
  state="$(
    az containerapp show \
      --name "$name" \
      --resource-group "$AZURE_RESOURCE_GROUP" \
      --query properties.runningStatus \
      --output tsv
  )"
  if [[ "$state" != "Running" ]]; then
    echo "::error::$name is not running (state=$state)"
    exit 1
  fi
done

echo "Private command health and worker readiness checks passed."
