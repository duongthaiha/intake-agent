$ErrorActionPreference = "Stop"
if ($env:MCP_FOUNDRY_BOOTSTRAP_COMPLETE -ne "true") {
  throw @"
MCP Foundry bootstrap is incomplete. Provisioning is intentionally fail-closed.
In the SAME tenant as the Foundry project, create the confidential client
credential through an approved secure channel; create the custom OAuth project
connection for api://MCP_SERVER_APP_CLIENT_ID/Intake.Tools.ReadWrite; create the
versioned Toolbox targeting INTAKE_MCP_ENDPOINT with MCP server label
MCP_TOOLBOX_SERVER_LABEL; and then set
MCP_FOUNDRY_BOOTSTRAP_COMPLETE=true in the protected deployment environment.
Never place the credential in source, normal logs, or azd outputs. Cross-tenant
token exchange is unsupported. Entra apps and consent are tenant-scoped and are
not resource-group Bicep resources.
"@
}
foreach ($name in "MCP_SERVER_APP_CLIENT_ID","MCP_OAUTH_CLIENT_APP_ID","MCP_OAUTH_CONNECTION_NAME","MCP_TOOLBOX_NAME","MCP_TOOLBOX_SERVER_LABEL","INTAKE_MCP_ENDPOINT") {
  if (-not [Environment]::GetEnvironmentVariable($name)) { throw "$name is required by the MCP bootstrap contract" }
}
Write-Host "MCP Foundry bootstrap acknowledgement present (same-tenant contract)."
