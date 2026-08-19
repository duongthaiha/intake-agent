#!/usr/bin/env bash
# Fail-closed contract for operations that do not yet have a stable, documented
# non-interactive Foundry Toolbox API in the installed azd extension.
set -euo pipefail

if [[ "${MCP_FOUNDRY_BOOTSTRAP_COMPLETE:-false}" != "true" ]]; then
  cat >&2 <<'EOF'
MCP Foundry bootstrap is incomplete. Provisioning is intentionally fail-closed.
In the SAME tenant as the Foundry project:
  1. Create a credential on MCP_OAUTH_CLIENT_APP_ID using an approved secure channel.
  2. Create the custom OAuth project connection in Foundry using that credential,
     api://MCP_SERVER_APP_CLIENT_ID/Intake.Tools.ReadWrite, and the Entra v2
     authorize/token endpoints. Never put the credential in azd values or logs.
  3. Create/version the Toolbox named by MCP_TOOLBOX_NAME, point its MCP tool at
     INTAKE_MCP_ENDPOINT, set its server label to MCP_TOOLBOX_SERVER_LABEL, and
     select that OAuth connection.
  4. Grant tenant admin consent only if tenant policy requires it, then set
     MCP_FOUNDRY_BOOTSTRAP_COMPLETE=true in the protected deployment environment.
Cross-tenant token exchange is unsupported. App registrations and consent are
tenant-scoped and cannot be provisioned by resource-group Bicep.
EOF
  exit 2
fi

for name in MCP_SERVER_APP_CLIENT_ID MCP_OAUTH_CLIENT_APP_ID MCP_OAUTH_CONNECTION_NAME MCP_TOOLBOX_NAME MCP_TOOLBOX_SERVER_LABEL INTAKE_MCP_ENDPOINT; do
  [[ -n "${!name:-}" ]] || { echo "$name is required by the MCP bootstrap contract" >&2; exit 2; }
done
echo "MCP Foundry bootstrap acknowledgement present (same-tenant contract)."
