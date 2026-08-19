#!/usr/bin/env bash
# One-time, secretless Entra bootstrap for delegated prompt-agent MCP access.
set -euo pipefail

ENV_NAME="${AZURE_ENV_NAME:-dev}"
DISPLAY_NAME="${1:-prompt-intake-mcp-${ENV_NAME}}"
SCOPE_VALUE="access_as_user"

mapfile -t APP_IDS < <(
  az ad app list \
    --filter "displayName eq '${DISPLAY_NAME}'" \
    --query "[].appId" \
    --output tsv
)

if (( ${#APP_IDS[@]} > 1 )); then
  echo "Multiple Entra applications named '${DISPLAY_NAME}' exist; refusing ambiguity." >&2
  exit 1
fi

if (( ${#APP_IDS[@]} == 0 )); then
  APP_ID="$(
    az ad app create \
      --display-name "$DISPLAY_NAME" \
      --sign-in-audience AzureADMyOrg \
      --query appId \
      --output tsv
  )"
else
  APP_ID="${APP_IDS[0]}"
fi

APP_OBJECT_ID="$(az ad app show --id "$APP_ID" --query id --output tsv)"
if ! az ad sp show --id "$APP_ID" >/dev/null 2>&1; then
  az ad sp create --id "$APP_ID" >/dev/null
fi

SCOPE_ID="$(
  az rest \
    --method GET \
    --url "https://graph.microsoft.com/v1.0/applications/${APP_OBJECT_ID}" \
    --query "api.oauth2PermissionScopes[?value=='${SCOPE_VALUE}'].id | [0]" \
    --output tsv
)"
if [[ -z "$SCOPE_ID" ]]; then
  SCOPE_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
fi

PATCH_BODY="$(
  jq -cn \
    --arg app_id "$APP_ID" \
    --arg scope_id "$SCOPE_ID" \
    --arg scope_value "$SCOPE_VALUE" \
    '{
      identifierUris: ["api://" + $app_id],
      api: {
        requestedAccessTokenVersion: 2,
        oauth2PermissionScopes: [{
          adminConsentDescription: "Allow the prompt intake agent to act for the signed-in user.",
          adminConsentDisplayName: "Access the prompt intake MCP API",
          id: $scope_id,
          isEnabled: true,
          type: "User",
          userConsentDescription: "Allow the prompt intake agent to access your intake requests.",
          userConsentDisplayName: "Access your intake requests",
          value: $scope_value
        }]
      }
    }'
)"

az rest \
  --method PATCH \
  --url "https://graph.microsoft.com/v1.0/applications/${APP_OBJECT_ID}" \
  --headers "Content-Type=application/json" \
  --body "$PATCH_BODY" \
  --output none

echo "Prompt intake MCP Entra application is ready."
echo "INTAKE_MCP_APP_CLIENT_ID=${APP_ID}"
echo "INTAKE_MCP_AUDIENCE=api://${APP_ID}"
echo "INTAKE_MCP_SCOPE=api://${APP_ID}/${SCOPE_VALUE}"
