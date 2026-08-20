# Microsoft Foundry agent variants

The checked-in assets follow the current generally available Foundry agent
object model:

- `hosted/` declares a Responses `2.0.0` Hosted Agent. The Python package is
  composed by a deployment-owned credential factory so model-facing code never
  imports a credential implementation.
- `toolboxes/` defines separate requester and reviewer MCP surfaces. OAuth
  secrets and endpoints live on project connections, not in agent code.
- `../packages/intake-foundry-prompt/` builds immutable requester and reviewer
  `PromptAgentDefinition` versions that consume the Toolbox default-version
  endpoints through agent-identity connections.
- `teams/` contains non-secret store metadata. `scripts/foundry/publish-teams.ps1`
  calls the documented Microsoft 365 publish API using an existing Azure Bot
  Service ARM ID; it does not create or modify infrastructure.

Production configuration runs `scripts/foundry/configure_live.py` in the private
managed-identity configuration job. It creates the OAuth connections, Toolbox
versions and defaults, Prompt Agent versions, and digest-pinned Hosted Agent versions,
then waits for Hosted readiness. The PowerShell scripts remain useful for governed
operator-driven setup and diagnostics.

Prompt Agent definitions do not have a supported deterministic per-turn
pre-tool hook. Their remote MCP connection placeholders must therefore target
an agent-safe gateway that enforces the capabilities declared in
`prompt-agents.json`: context reload, `allowedActions` gating, trusted
provenance/correlation injection, and no automatic mutation replay. Do not point
the Prompt Agent Toolbox at an unrestricted application MCP surface. This
repository version-controls and validates that requirement; the deployed production
MCP adapter enforces it before deterministic application execution.

OAuth consent is a normal incomplete response, not a failed mutation. Surface
the consent URL, wait for the user to consent, and retry the original turn with
the same Foundry conversation or previous response ID. The first operation on
the resumed requester turn is always `get_intake_context`.

The Hosted image intentionally uses the Foundry-supported root execution model because
the platform reserves and mounts `/home/session`, while Responses hosting creates
`/home/session/.sessions`. Other application and configuration images remain non-root.

After creating a Prompt Agent version, grant its generated identity project
access before invoking its Toolbox:

```powershell
scripts/foundry/grant-prompt-agent-access.ps1 `
  -ProjectEndpoint $env:FOUNDRY_PROJECT_ENDPOINT `
  -ProjectResourceId $env:FOUNDRY_PROJECT_RESOURCE_ID `
  -AgentName intake-requester-prompt
```

## Local validation

The repository MCP server uses MCP Python SDK 2.x. The latest Foundry hosting
beta available from the package feed currently requires MCP 1.x, so uv records
the server and Hosted Agent runtime extras as mutually exclusive environments.
The default workspace retains MCP 2.x:

```powershell
uv sync
uv run ruff check .
uv run mypy
uv run pytest
```

Run the Hosted Agent and Toolbox composition smoke in an isolated uv
environment so its MCP 1.x dependency never replaces the default workspace's
MCP 2.x installation:

```powershell
$env:UV_LINK_MODE = "copy"
uv run --isolated --package intake-foundry-hosted --extra runtime intake-foundry-smoke
Remove-Item Env:UV_LINK_MODE
```

Microsoft documentation used for these assets:

- https://learn.microsoft.com/azure/foundry/how-to/develop/framework-hosted-agents
- https://learn.microsoft.com/azure/foundry/agents/how-to/tools/toolbox
- https://learn.microsoft.com/azure/foundry/agents/how-to/tools/tool-authentication
- https://learn.microsoft.com/azure/foundry/agents/how-to/configure-agent
- https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot
- https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot-virtual-network
