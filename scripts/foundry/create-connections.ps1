param(
    [Parameter(Mandatory = $true)]
    [string] $ProjectEndpoint
)

$ErrorActionPreference = "Stop"

$required = @(
    "INTAKE_REQUESTER_MCP_URL",
    "INTAKE_REQUESTER_OAUTH_AUTHORIZATION_URL",
    "INTAKE_REQUESTER_OAUTH_TOKEN_URL",
    "INTAKE_REQUESTER_OAUTH_CLIENT_ID",
    "INTAKE_REQUESTER_OAUTH_CLIENT_SECRET",
    "INTAKE_REQUESTER_OAUTH_SCOPES",
    "INTAKE_REVIEWER_MCP_URL",
    "INTAKE_REVIEWER_OAUTH_AUTHORIZATION_URL",
    "INTAKE_REVIEWER_OAUTH_TOKEN_URL",
    "INTAKE_REVIEWER_OAUTH_CLIENT_ID",
    "INTAKE_REVIEWER_OAUTH_CLIENT_SECRET",
    "INTAKE_REVIEWER_OAUTH_SCOPES"
)
foreach ($name in $required) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
        throw "Required environment variable $name is not set."
    }
}

azd ai connection create intake-requester-mcp `
    --kind remote-tool `
    --target $env:INTAKE_REQUESTER_MCP_URL `
    --auth-type oauth2 `
    --authorization-url $env:INTAKE_REQUESTER_OAUTH_AUTHORIZATION_URL `
    --token-url $env:INTAKE_REQUESTER_OAUTH_TOKEN_URL `
    --client-id $env:INTAKE_REQUESTER_OAUTH_CLIENT_ID `
    --client-secret $env:INTAKE_REQUESTER_OAUTH_CLIENT_SECRET `
    --scopes $env:INTAKE_REQUESTER_OAUTH_SCOPES

azd ai connection create intake-reviewer-mcp `
    --kind remote-tool `
    --target $env:INTAKE_REVIEWER_MCP_URL `
    --auth-type oauth2 `
    --authorization-url $env:INTAKE_REVIEWER_OAUTH_AUTHORIZATION_URL `
    --token-url $env:INTAKE_REVIEWER_OAUTH_TOKEN_URL `
    --client-id $env:INTAKE_REVIEWER_OAUTH_CLIENT_ID `
    --client-secret $env:INTAKE_REVIEWER_OAUTH_CLIENT_SECRET `
    --scopes $env:INTAKE_REVIEWER_OAUTH_SCOPES

$base = $ProjectEndpoint.TrimEnd("/")
azd ai connection create intake-requester-toolbox-agent-identity `
    --kind remote-tool `
    --target "$base/toolboxes/intake-requester/mcp?api-version=v1" `
    --auth-type agentic-identity `
    --audience https://ai.azure.com

azd ai connection create intake-reviewer-toolbox-agent-identity `
    --kind remote-tool `
    --target "$base/toolboxes/intake-reviewer/mcp?api-version=v1" `
    --auth-type agentic-identity `
    --audience https://ai.azure.com
