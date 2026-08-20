# Platform capability validation

This deployment uses a fail-closed preflight before provisioning Azure resources.
The preflight confirms that the active Azure CLI context, resource providers,
candidate region, and Azure Developer CLI Foundry extensions can support the
infrastructure declared by the Intake Agent architecture.

Run:

```powershell
.\scripts\Test-PlatformCapabilities.ps1 -Location eastus2
```

The command emits JSON evidence and exits non-zero if a required provider,
resource type, or Foundry extension is unavailable. CI and deployment automation
must retain this output as release evidence without committing subscription or
tenant identifiers.

## Initial candidate

East US 2 is the initial candidate region because current Microsoft documentation
lists support for:

- Foundry Agent Service and Hosted Agents.
- Private networking with Class A address ranges.
- MCP and Azure AI Search agent tools.
- The Azure resource types required by the hardened deployment.

The region is not hard-coded in infrastructure. Model availability, quota,
Toolbox OAuth passthrough, Prompt Agent parity, and Teams publishing must still be
validated against the provisioned Foundry project before the candidate is promoted.

## Hardened-network gate

The Foundry resource and virtual network must be created in the same region, and
Hosted Agent network injection must be configured when the Foundry account is
first created. The deployment must not retrofit networking or temporarily enable
public access to bypass a failed private-network check.

For projects created after June 25, 2026, current Microsoft documentation supports
a network-secured Azure Container Registry for Hosted Agent images. Deployment
validation must prove image pull, private DNS, Toolbox-to-MCP reachability, and
agent-to-private-service routing from the deployed environment.

## Remaining deployed checks

The static preflight is necessary but not sufficient. Deployment remains blocked
until both agent variants prove:

1. Teams Activity Protocol invocation.
2. User OAuth consent, revocation, and re-consent.
3. Correct requester/reviewer token audience and delegated scopes.
4. Cross-user isolation and immutable actor derivation.
5. Private MCP reachability and no direct product-data access.
6. Required Teams controls, notifications, deep links, and accessibility behavior.
