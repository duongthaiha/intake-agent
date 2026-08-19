#!/usr/bin/env bash
# Idempotently creates the tenant-scoped MCP resource/client applications.
# No credential is created or printed. The Foundry OAuth connection credential
# must be generated and entered directly through the approved secure bootstrap.
set -euo pipefail

: "${AZURE_ENV_NAME:?AZURE_ENV_NAME is required}"
: "${MCP_OAUTH_REDIRECT_URI:?MCP_OAUTH_REDIRECT_URI is required; obtain the exact Foundry custom OAuth callback URI before running}"
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }

tenant="$(az account show --query tenantId -o tsv)"
server_name="intake-mcp-${AZURE_ENV_NAME}"
client_name="intake-mcp-foundry-${AZURE_ENV_NAME}"

get_or_create_app() {
  local name="$1" redirect="${2:-}" matches app_id object_id
  matches="$(az ad app list --filter "displayName eq '${name}'" -o json)"
  [[ "$(jq 'length' <<<"$matches")" -le 1 ]] ||
    { echo "More than one app registration is named '${name}'; resolve ambiguity manually." >&2; exit 1; }
  app_id="$(jq -r '.[0].appId // empty' <<<"$matches")"
  object_id="$(jq -r '.[0].id // empty' <<<"$matches")"
  if [[ -z "$app_id" ]]; then
    if [[ -n "$redirect" ]]; then
      created="$(az ad app create --display-name "$name" --sign-in-audience AzureADMyOrg --web-redirect-uris "$redirect" -o json)"
    else
      created="$(az ad app create --display-name "$name" --sign-in-audience AzureADMyOrg -o json)"
    fi
    app_id="$(jq -r '.appId' <<<"$created")"
    object_id="$(jq -r '.id' <<<"$created")"
  fi
  printf '%s|%s' "$app_id" "$object_id"
}

IFS='|' read -r server_app_id server_object_id <<<"$(get_or_create_app "$server_name")"
IFS='|' read -r client_app_id client_object_id <<<"$(get_or_create_app "$client_name" "$MCP_OAUTH_REDIRECT_URI")"
for app_id in "$server_app_id" "$client_app_id"; do
  az ad sp show --id "$app_id" --only-show-errors >/dev/null 2>&1 ||
    az ad sp create --id "$app_id" --only-show-errors >/dev/null
done
scope_id="$(az rest --method get --uri "https://graph.microsoft.com/v1.0/applications/${server_object_id}" \
  --query "api.oauth2PermissionScopes[?value=='Intake.Tools.ReadWrite'].id | [0]" -o tsv)"
[[ -n "$scope_id" ]] || scope_id="$(cat /proc/sys/kernel/random/uuid)"

body="$(jq -nc --arg server "$server_app_id" --arg client "$client_app_id" --arg scope "$scope_id" \
  '{signInAudience:"AzureADMyOrg",identifierUris:["api://"+$server],api:{requestedAccessTokenVersion:2,oauth2PermissionScopes:[{adminConsentDescription:"Access intake requester tools as the signed-in user",adminConsentDisplayName:"Access intake requester tools",id:$scope,isEnabled:true,type:"User",userConsentDescription:"Access your intake requests",userConsentDisplayName:"Access your intake requests",value:"Intake.Tools.ReadWrite"}],preAuthorizedApplications:[{appId:$client,delegatedPermissionIds:[$scope]}]}}')"
az rest --method patch --uri "https://graph.microsoft.com/v1.0/applications/${server_object_id}" \
  --headers Content-Type=application/json --body "$body" --only-show-errors >/dev/null
client_body="$(jq -nc --arg redirect "$MCP_OAUTH_REDIRECT_URI" \
  '{signInAudience:"AzureADMyOrg",web:{redirectUris:[$redirect]}}')"
az rest --method patch --uri "https://graph.microsoft.com/v1.0/applications/${client_object_id}" \
  --headers Content-Type=application/json --body "$client_body" --only-show-errors >/dev/null

azd env set MCP_SERVER_APP_CLIENT_ID "$server_app_id"
azd env set MCP_OAUTH_CLIENT_APP_ID "$client_app_id"
azd env set MCP_OAUTH_CONNECTION_NAME "intake-mcp-oauth-${AZURE_ENV_NAME}"
azd env set MCP_TOOLBOX_NAME "intake-mcp-v1-${AZURE_ENV_NAME}"
azd env set MCP_TOOLBOX_SERVER_LABEL "intake_requester_tools"
echo "Configured same-tenant Entra applications and delegated scope for tenant $tenant."
echo "No client credential or tenant-wide admin consent was created."
