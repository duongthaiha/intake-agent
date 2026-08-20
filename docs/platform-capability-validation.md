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

## Validated development deployment

The development deployment completed on 2026-08-20 with the following split-region
layout:

- Foundry, Hosted Agents, the internal Container Apps environment, and private data
  services in East US 2.
- Azure AI Search in East US after the East US 2 deployment reported insufficient
  regional capacity.
- `gpt-4.1-mini` `2025-04-14` on `DataZoneStandard`, capacity 10.
- A network-secured private ACR used by Responses `2.0.0` Hosted Agents.

The regions remain parameterized. Production still requires regional capacity,
quota, data-residency, and owner approval.

## Hardened-network gate

The Foundry resource and virtual network must be created in the same region, and
Hosted Agent network injection must be configured when the Foundry account is
first created. The deployment must not retrofit networking or temporarily enable
public access to bypass a failed private-network check.

For projects created after June 25, 2026, current Microsoft documentation supports
a network-secured Azure Container Registry for Hosted Agent images. The development
deployment proved immutable image pull while ACR public access, default network
access, and image export remained disabled after the controlled build window.

The Hosted runtime is the sole root-running image. Foundry reserves and mounts
`/home/session`, and Responses hosting must create `/home/session/.sessions`; the
platform mount is not writable by an image-selected non-root UID. The image therefore
follows the supported Microsoft sample execution model. All product workloads and
the private Foundry configurator remain non-root, and the Hosted identity has no
product data-plane role.

## Foundry evidence

The private configuration job created separate requester and reviewer OAuth
connections, Toolboxes, Prompt Agent versions, and Hosted Agent versions. Hosted
requester and reviewer version 3 both reached `active`. A VNet-local Responses smoke
completed for both and returned `oauth_consent_request`, proving model execution,
Toolbox composition, and delegated-auth handoff without exposing private endpoints.

## Remaining deployed checks

Production promotion remains fail-closed until:

1. Teams Activity Protocol invocation.
2. User OAuth consent, revocation, and re-consent.
3. Correct requester/reviewer token audience and delegated scopes.
4. Cross-user isolation and immutable actor derivation.
5. Private MCP reachability and no direct product-data access.
6. Required Teams controls, notifications, deep links, and accessibility behavior.

Tenant-wide admin consent is currently blocked because the deployment operator is
not an Entra administrator. Evaluation dataset and threshold approvals also remain
pending by design.
