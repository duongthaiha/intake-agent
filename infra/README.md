# Intake Agent Azure infrastructure

This folder contains the subscription-scope Bicep foundation for isolated `dev`, `test`, and `prod` Intake Agent environments. The default is the hardened topology in `eastus2`; the region remains parameterized and must pass quota, service-availability, networking, and data-residency review before provisioning.

## Current deployment status

The hardened development environment and digest-pinned command, worker, evaluation,
private configurator, Hosted Agent, Prompt Agent, and Toolbox artifacts were deployed
and validated on 2026-08-20. Test and production remain fail-closed until tenant,
evaluation, operational, and release approvals are complete.

No secrets are stored in the Bicep parameter files or `azure.yaml`.

## Topology

The deployment creates one resource group and a dedicated VNet per environment:

| Subnet | Default CIDR | Purpose | Delegation |
|---|---:|---|---|
| `snet-foundry-agents` | `10.42.0.0/24` | Foundry hosted-agent network injection | `Microsoft.App/environments` |
| `snet-container-apps` | `10.42.2.0/23` | Dedicated Intake Agent Container Apps managed environment | `Microsoft.App/environments` |
| `snet-functions-integration` | `10.42.4.0/24` | Reserved for conventional Functions VNet integration if the worker hosting decision changes | `Microsoft.Web/serverFarms` |
| `snet-private-endpoints` | `10.42.5.0/24` | Private endpoints only | None |
| `AzureFirewallSubnet` | `10.42.6.0/26` | Hardened allow-listed egress | Reserved Azure Firewall name |

The dedicated Container Apps environment is internal, has encrypted peer traffic and mTLS enabled, and is not shared with unrelated workloads. The command service, containerized Functions workers, and evaluation job placeholders all target this environment.

Cosmos DB, Storage, Azure AI Search, Service Bus, Key Vault, ACR, Microsoft Foundry, and Azure Monitor Private Link Scope have private endpoints and private DNS. Public network access is disabled for data-bearing services in both network modes.

The product database/evidence account and the Foundry agent-state Cosmos DB/Storage accounts are separate. The Foundry project identity receives no role on product Cosmos containers.

`networkMode` affects Foundry and monitoring ingress and controlled egress:

- `hardened` (default): Foundry and Azure Monitor public access are disabled. Foundry, Container Apps, and reserved Functions subnets route internet-bound traffic through Azure Firewall, which allows only the governed Microsoft/target FQDN list.
- `baseline`: Foundry remains public with Entra authentication; customer data services and workload ingress remain private.

Foundry agent network injection is enabled in both modes so its customer-owned Storage, Cosmos DB, and Search dependencies remain reachable without public data-plane access.

## Modules

| Module | Responsibility |
|---|---|
| `network.bicep` | Dedicated VNet, isolated subnets, delegation, and NSGs |
| `egress.bicep` / `network-routes.bicep` | Hardened Azure Firewall policy, allow-list, and workload UDRs |
| `identity.bicep` | One user-assigned identity per workload trust boundary |
| `observability.bicep` | Log Analytics, Application Insights, and Azure Monitor Private Link Scope |
| `data.bicep` | Storage, Cosmos DB containers, Search, Service Bus, Key Vault, ACR, diagnostics |
| `container-environment.bicep` | Dedicated internal Container Apps managed environment |
| `foundry.bicep` | AIServices account, project, customer-owned resource connections, network injection |
| `private-endpoints.bicep` | Private endpoints, private DNS zones, and VNet links |
| `rbac.bicep` | Managed-identity data-plane RBAC and Cosmos DB native RBAC |
| `foundry-capability-host.bicep` | Supported Standard Agent project capability host |
| `compute.bicep` | Dormant command service, Functions worker, and evaluation job resources |
| `governance.bicep` | Budget, production delete lock, and optional policy assignments |

## Provisioning ownership

| Component | Provisioner | Notes |
|---|---|---|
| Resource group, VNet, subnets, DNS, private endpoints | Bicep through `azd provision` | Created private from the first deployment |
| Foundry account, project, connections, capability host | Bicep through `azd provision` | Agent definitions are a later configuration artifact |
| Container Apps managed environment | Bicep through `azd provision` | Dedicated to Intake Agent |
| ACR, Cosmos DB, Storage, Search, Service Bus, Key Vault, monitoring | Bicep through `azd provision` | Public data-plane access disabled |
| Command service | Bicep resource plus `azd` image deployment | Digest-pinned private MCP service |
| Outbox, notification, integration, completion, retention workers | Bicep resources plus `azd` image deployment | Digest-pinned Container Apps resources optimized for Functions |
| Evaluation job | Bicep | Digest-pinned; release fails closed while approvals are pending |
| Hosted Agent | Private managed-identity configuration job | Governed by `foundry/deployables.json`; digest-pinned Responses 2.0 image |
| Prompt Agent | Private managed-identity configuration job | Immutable requester/reviewer versions |
| Requester/reviewer Toolboxes and OAuth connections | Private configuration job plus tenant-governed Entra setup | Separate surfaces, connections, and allow-lists |
| Actual agent instance RBAC | `scripts/azure/post-publish-rbac.ps1` | Runs only after deployment returns the real instance identities |
| Teams publication/catalog approval | Foundry publication and Microsoft 365 administration | Not represented as an invented ARM resource |

## Prerequisites

1. Azure CLI 2.89 or newer, Bicep CLI 0.46 or newer, Azure Developer CLI 1.31 or newer, and PowerShell 7.
2. An enabled subscription with the providers listed in `scripts/azure/preflight.ps1` registered.
3. Contributor plus Role Based Access Control Administrator, User Access Administrator, or Owner at the target scope.
4. Quota and regional availability confirmed in the selected region for Foundry Agent Service, AIServices model deployments, Container Apps, Search Standard, Service Bus Premium, ACR Premium, and Cosmos DB.
5. A runner with private VNet reachability for later image publication, Foundry configuration, private endpoint verification, and deployed smoke tests. The documented developer-access default is cloud-only CI/self-hosted runner access; local access requires an approved VPN or jump host.
6. Tenant-owned Entra applications, delegated requester/reviewer scopes, OAuth redirect URIs, admin consent, Graph permissions, and federated CI credentials created through a separate governed tenant procedure.

## Validation and preflight

Static validation does not contact Azure:

```powershell
./scripts/azure/validate-infrastructure.ps1
./scripts/azure/preflight.ps1 -StaticOnly
```

After prerequisites are approved, online validation and what-if can run without deploying:

```powershell
./scripts/azure/preflight.ps1 -EnvironmentName dev -WhatIf
```

The online preflight checks provider registration and runs subscription-scope ARM validation and what-if. It does not create resources.

## Environment parameters

| File | Network mode | Workloads | Intended use |
|---|---|---:|---|
| `main.dev.bicepparam` | Hardened | Disabled | Development |
| `main.test.bicepparam` | Hardened | Disabled | Integration/evaluation |
| `main.prod.bicepparam` | Hardened | Disabled | Production candidate |

`main.parameters.json` is the `azd` parameter bridge. Set non-secret values with `azd env set`; never store credentials or connection strings there.

Before runtime deployment, set all three images to ACR references pinned by `@sha256:<digest>`, set `AZURE_DEPLOY_WORKLOADS=true`, and provide every required Foundry artifact in `foundry/deployables.json`.

## API version policy

Modules use current stable resource APIs verified against Microsoft Learn on 2026-08-20. Diagnostic settings remain on `2021-05-01-preview`, the current ARM API for that resource type; the generic Bicep API-age rule is disabled because it incorrectly recommends the older `2016-09-01` version.

Key references:

- [Foundry private networking](https://learn.microsoft.com/azure/foundry/agents/how-to/virtual-networks)
- [Foundry networking options](https://learn.microsoft.com/azure/foundry/agents/concepts/networking-options)
- [Use your own resources with Foundry Agent Service](https://learn.microsoft.com/azure/foundry/agents/how-to/use-your-own-resources)
- [Container Apps networking](https://learn.microsoft.com/azure/container-apps/networking)
- [Azure Private Endpoint DNS zone values](https://learn.microsoft.com/azure/private-link/private-endpoint-dns)
- [Microsoft.CognitiveServices accounts/projects](https://learn.microsoft.com/azure/templates/microsoft.cognitiveservices/accounts/projects)
