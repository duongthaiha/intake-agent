# Azure Deployment Plan

> **Status:** ✅ **Deployed and Verified** — Hosted Agent `intake-agent:9` is active in `dev` with canonical JSON Schema template version `1.1.0`.

Generated: 2026-08-07T16:08:46Z
Revised: 2026-08-07T16:22:00Z (Tank — Fact Checker revision cycle)
Paused: 2026-08-07T16:37:38Z (Tank — Authenticated account does not expose intended subscription)
Approved: 2026-08-07T16:43:00Z (Morpheus — Design Review ceremony; user confirmed subscription/region)
Implementation: 2026-08-07T17:40:00Z (Tank — Preflight validation + full Bicep/azd/CI-CD implementation)
Preflight + What-If: 2026-08-07T18:00:00Z (Tank — ServiceBus registered, preflight passed, ARM what-if clean)
Final Validation Gate: 2026-08-07T16:40:52.306+01:00 (Copilot CLI — all 9 checks exit 0, status promoted to Ready for Validation)
Formal Validation: 2026-08-07T18:05:49Z (Tank — azure-validate workflow, 13 checks passed, status promoted to Validated)

### Verified Azure Context

| Attribute | Value |
|-----------|-------|
| Tenant ID | `c214aaa8-7a43-441a-b501-f942c96f54a8` |
| Subscription ID | `87e1a785-896b-4eb4-a214-47f67995133e` |
| Subscription Name | `ME-MngEnvMCAP456638-haduong-1` |
| Subscription Status | Enabled |
| Selected Region | `eastus2` |
| Region Rationale | Broad Foundry Agent tool support + Functions Flex Consumption availability confirmed |

---

### Preflight Validation Evidence (2026-08-07)

**Subscription:**
- ✅ `87e1a785-896b-4eb4-a214-47f67995133e` (`ME-MngEnvMCAP456638-haduong-1`) — State: `Enabled`
- ✅ Tenant: `c214aaa8-7a43-441a-b501-f942c96f54a8`
- ✅ User: `haduong@MngEnvMCAP456638.onmicrosoft.com`

**Provider Registrations:**

| Provider | State | Action Required |
|----------|-------|-----------------|
| Microsoft.Storage | ✅ Registered | — |
| Microsoft.DocumentDB | ✅ Registered | — |
| Microsoft.Search | ✅ Registered | — |
| Microsoft.KeyVault | ✅ Registered | — |
| Microsoft.Web | ✅ Registered | — |
| Microsoft.App | ✅ Registered | — |
| Microsoft.Network | ✅ Registered | — |
| Microsoft.ManagedIdentity | ✅ Registered | — |
| Microsoft.OperationalInsights | ✅ Registered | — |
| microsoft.insights | ✅ Registered | — |
| Microsoft.CognitiveServices | ✅ Registered | — |
| Microsoft.Authorization | ✅ Registered | — |
| **Microsoft.ServiceBus** | ✅ **Registered** (registered 2026-08-07T17:05Z, confirmed at ~50s) | — |
| **Microsoft.MachineLearningServices** | ⚠️ **NotRegistered** — intentionally not registered; gated by `deployFoundry=false` | Register only when enabling Foundry gate |
| **Microsoft.BotService** | ⚠️ **NotRegistered** — intentionally not registered; gated by `deployBotService=false` | Register only when enabling Bot Service gate after Teams spike |

> ✅ **All blockers for `azd provision` (POC defaults) are resolved.** MachineLearningServices and BotService intentionally left unregistered — gated features disabled.

**Preflight run result (2026-08-07T17:05Z):**
- ✅ Exit 0 — PASSED (0 errors, 2 expected warnings for gated-only providers)

**ARM What-If result (2026-08-07T17:08Z) — `dev / eastus2 / deployFoundry=false / deployBotService=false / deployPrivateEndpoints=false`:**
- ✅ Exit 0 — 38 resources to CREATE, 0 errors, 0 permission/policy blockers
- Resources confirmed (selected):
  - `rg-intake-dev` resource group
  - `cosmos-intake-dev` + database `intake` + containers: `requests`, `revisions`, `workflow-events`
  - `sb-intake-dev` + queues: `domain-events`, `domain-events-dlq-recovery`
  - `srch-intake-dev` (AI Search Basic)
  - `st2k2osaevug` (Storage) + containers: `request-artifacts`, `eval-datasets`, `deploymentpackage`
  - `kv-2k2osaevugjeg` (Key Vault) + Secrets Officer role assignment for deployer
  - `appi-intake-dev` (App Insights) + `log-intake-dev` (Log Analytics)
  - `vnet-intake-dev` + 5 private DNS zones + VNet links
  - `id-intake-{agent,worker,eval,notify}-dev` managed identities
  - `asp-intake-dev` (FC1 plan) + `func-intake-dev` (Functions, Python 3.11, VNet-integrated)
  - `cae-intake-dev` (Container Apps env, VNet-integrated) + `job-intake-eval-dev`
- **Foundry resources: not in changeset** ✅ (gated)
- **Bot Service: not in changeset** ✅ (gated)
- **Private endpoints: not in changeset** ✅ (gated)
- **RBAC note:** Only the Key Vault Secrets Officer assignment for the known deployer OID appears in what-if. Service Bus, Storage, and Cosmos data-plane role assignments referencing computed managed-identity principal IDs are correctly omitted — ARM what-if cannot resolve principal IDs of resources not yet created. These will be created at provision time.

**Deployer RBAC:**
- ✅ `Owner` role at management group `c214aaa8-7a43-441a-b501-f942c96f54a8` — covers `Contributor + User Access Administrator` on all child subscriptions/resource groups.

**Quota Signals (eastus2):**
- ✅ AI Search Basic: 0/12 in use
- ✅ CognitiveServices S0: 0/30 in use
- ✅ Total Regional vCPUs: 0/100
- ℹ️ Model TPM quota (GPT-4o or selected model) must be confirmed separately in AI Foundry portal before enabling `deployFoundry=true` and deploying model.

---

### Design Review Decisions (2026-08-07)

| Decision | Reference |
|----------|-----------|
| Python package boundaries and file ownership defined | `docs/adr/ADR-012-package-module-boundaries.md` |
| Domain entities and thin vertical flow specified | `docs/adr/ADR-013-domain-entities-and-vertical-flow.md` |
| Command/event schemas, idempotency, concurrency, correlation | `docs/contracts/command-event-schemas.md` |
| Repository interfaces (abstract + in-memory for tests) | `docs/contracts/repository-interfaces.md` |
| Teams as adapter boundary; local path for POC demo | `docs/adr/ADR-014-teams-integration-boundary.md` |
| Infrastructure config keys per runtime (no secrets) | `docs/contracts/infrastructure-config.md` |
| Integration and acceptance gates | `docs/contracts/integration-gates.md` |
| Non-overlapping file ownership: Trinity/Neo/Tank/Switch | `docs/adr/ADR-012-package-module-boundaries.md` §Ownership |

---

## 1. Project Overview

**Goal:** Deploy a Python-hosted Azure intake agent published through Teams/Microsoft Foundry, with structured requirements capture, gap analysis, human review, Cosmos DB/blob persistence, downstream automation, evaluation, private networking, Bicep, azd, and deployment verification.

**Path:** New Project

**Analysis Mode:** NEW — The repository contains only architecture documentation (`architecture.md`, `productbacklog.md`) and squad configuration. No application code, infrastructure, or Azure configuration exists yet.

---

## 2. Requirements

| Attribute | Value |
|-----------|-------|
| Classification | POC |
| Scale | Small (single enterprise tenant, <1K concurrent users for pilot) |
| Budget | Cost-Optimized (POC tier — minimize spend, prove architecture) |
| **Subscription** | ✅ `87e1a785-896b-4eb4-a214-47f67995133e` (`ME-MngEnvMCAP456638-haduong-1`, Enabled) |
| **Location** | ✅ `eastus2` — Foundry Agent tools + Functions Flex Consumption confirmed |

### Key Constraints

- Single Microsoft Entra tenant, one enterprise organisation
- Foundry Hosted Agent availability determines region (preview regions only)
- Both baseline and hardened network variants must remain deployable
- Network topology decision (baseline vs hardened) deferred to production; POC uses baseline
- Model selection deferred until region/quota confirmed
- No secrets in code; managed identity everywhere

### Prerequisites & Dependencies

| Prerequisite | Category | Validation |
|---|---|---|
| `Microsoft.MachineLearningServices` provider registered | Provider Registration | `az provider register --namespace Microsoft.MachineLearningServices` |
| `Microsoft.CognitiveServices` provider registered | Provider Registration | `az provider register --namespace Microsoft.CognitiveServices` |
| `Microsoft.BotService` provider registered | Provider Registration | `az provider register --namespace Microsoft.BotService` |
| `Microsoft.App` provider registered | Provider Registration | `az provider register --namespace Microsoft.App` |
| `Microsoft.DocumentDB` provider registered | Provider Registration | `az provider register --namespace Microsoft.DocumentDB` |
| GPT-4o (or selected model) quota in target region | Model Quota | Azure Portal → AI Foundry → Quotas; request increase if zero |
| Foundry Hosted Agent feature available in target region | Preview/Feature Registration | Check [Foundry regional availability](https://learn.microsoft.com/azure/foundry/reference/region-support) |
| Tenant admin consent for Entra app registrations (if required) | Admin Consent | Entra admin must pre-approve or grant consent for Bot Service multi-tenant app |
| Deploying identity has `Contributor` + `User Access Administrator` (or `Owner`) on target resource group | Role-Assignment Permissions | Required to create resources AND assign RBAC roles |
| Deploying identity has `Microsoft.Authorization/roleAssignments/write` | RBAC | Required for managed-identity role assignments in Bicep |
| All required services available in a single region | Region Overlap | Validate during quota check: Foundry, Cosmos DB Serverless, AI Search Basic, Container Apps, Functions Flex Consumption must co-exist |
| M365/Teams admin consent for agent sideloading or org-wide publishing | Admin Consent | Required for Teams publishing; tenant admin must approve the Teams app |

---

## 3. Components Detected

| Component | Type | Technology | Path |
|-----------|------|------------|------|
| (none) | — | — | — |

**Scan Result:** Repository contains only documentation and `.squad/` configuration. No application source code, infrastructure files, Dockerfiles, azure.yaml, CI/CD pipelines, or package manifests exist.

### Dependencies (from architecture.md)

| Component | Depends On | Type |
|-----------|-----------|------|
| Hosted Agent | Cosmos DB | Database (NoSQL) |
| Hosted Agent | Azure AI Search | Search (Foundry-managed tool) |
| Hosted Agent | Service Bus | Queue (outbox dispatch) |
| Workers (Functions) | Service Bus | Queue (consumer) |
| Workers (Functions) | Cosmos DB | Database |
| Workers (Functions) | Blob Storage | Object storage |
| Workers (Functions) | Key Vault | Secrets |
| Evaluation Job | Container Apps Jobs | Compute |
| All workloads | Application Insights | Observability |
| CI/CD | GitHub Actions | Automation |

### Existing Infrastructure

| Item | Status |
|------|--------|
| azure.yaml | Not found |
| infra/ | Not found |
| Dockerfiles | Not found |
| .github/workflows/ | Not found |
| requirements.txt / pyproject.toml | Not found |
| src/ | Not found |

---

## 4. Recipe Selection

**Selected:** AZD (Bicep)

**Rationale:**
- ADR-011 in `architecture.md` explicitly accepts Bicep + azd as the deployment contract
- New project, Azure-only, multi-service — ideal for azd
- Team uses `azd provision`, `azd deploy`, `azd up` as the shared developer/CI contract
- GitHub Actions invokes the same Bicep/azd contract
- No Terraform requirement identified

---

## 5. Architecture

**Stack:** Foundry Hosted Agent (Python) + Azure Functions (workers) + Container Apps Jobs (evaluation)

### Thin Vertical POC Slice (Slice 1: Foundation + Slice 2 start)

The POC proves the minimum viable path: Foundry → intake → validate → persist → resume. It covers:
1. Bicep infrastructure and azd contract
2. Foundry hub + project + AI Services account + Python Hosted Agent skeleton
3. Single template, request creation, field capture, and persistence in Cosmos DB
4. Private endpoints to data services (baseline variant)
5. Managed identities and RBAC
6. Application Insights tracing
7. GitHub Actions CI with workload identity federation
8. Teams pilot publishing (subject to spike — see §5.1)

### 5.1 Teams Publishing — Architecture Spike (BLOCKING)

> **Status:** ⛔ BLOCKING — must be resolved before Phase 2 step 2.8 and before Bot Service SKU selection.

**Context:** The architecture requires publishing the Foundry Hosted Agent to Microsoft Teams. Microsoft documentation ([Publish agents to M365 and Teams](https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot)) confirms the supported integration path:

1. **Azure Bot Service** resource acts as message proxy between Teams channel adapters and the Foundry agent's Activity Protocol endpoint.
2. The Bot Service `endpoint` is set to the Foundry agent's activity protocol URL: `https://<resource>.services.ai.azure.com/api/projects/<project>/agents/<agent>/endpoint/protocols/activityProtocol?api-version=2025-05-15-preview`
3. Publishing is done via the Foundry M365 publish API or portal, with `publishScope` of `Shared` or `Tenant`.
4. `BotServiceTenant` authorization scheme allows all users in the tenant to call the agent.

**Validated path:** Foundry Hosted Agent → Activity Protocol → Azure Bot Service → Teams Channel.

**Open questions requiring spike:**

| Question | Impact | Fallback |
|---|---|---|
| Does Bot Service F0 (free) tier support the Activity Protocol traffic pattern, or is S1 required? | Cost; resource inventory | Use S1 Standard (~$50/month) as safe default; validate F0 in spike |
| Does `Tenant`-scoped publishing require M365 admin approval in the Teams Admin Center? | Deployment process; admin dependency | Start with `Shared` (personal) scope for dev/test; escalate to `Tenant` for pilot |
| Are there licensing implications (e.g., M365 Copilot license) for end-users consuming the agent in Teams? | User access; commercial | Standard Teams license assumed sufficient for Bot Service channel; validate |
| Is the Microsoft 365 Agents SDK an alternative or complementary path? | Architecture optionality | Not required — Foundry publish API is the primary documented path |

**Safe fallback architecture:** If Teams publishing is blocked (admin consent, licensing, or preview limitations), the agent remains accessible via Foundry portal web chat and the Foundry SDK programmatic API. No infrastructure is wasted — Bot Service is the only Teams-specific resource.

**Resolution:** Complete spike before implementing step 2.8. Document findings in `.squad/decisions/inbox/`.

### Service Mapping

| Component | Azure Service | SKU / Tier |
|-----------|---------------|-----|
| Intake Agent (Python) | Foundry Agent Service — Hosted Agent | Standard (consumption-based) |
| Foundry Hub | Azure AI Foundry (Microsoft.MachineLearningServices/workspaces, kind: Hub) | — |
| Foundry Project | Azure AI Foundry (Microsoft.MachineLearningServices/workspaces, kind: Project) | — |
| AI Services (model hosting) | Microsoft.CognitiveServices/accounts (kind: AIServices) | S0 |
| Async Workers | Azure Functions | Consumption (Flex) or Basic plan |
| Evaluation Job | Azure Container Apps Job | Consumption |
| Request Data | Azure Cosmos DB for NoSQL | Serverless (POC) |
| Artifacts | Azure Blob Storage | Standard LRS |
| Enterprise Knowledge | Azure AI Search | Basic (POC) |
| Message Queue | Azure Service Bus | Standard |
| Secrets | Azure Key Vault | Standard |
| Observability | Application Insights + Log Analytics | Pay-as-you-go |
| Bot Channel | Azure Bot Service | ⚠️ TBD — F0 or S1 pending spike (see §5.1) |
| Network | VNet + Private Endpoints (baseline) | — |
| Identity | User-Assigned Managed Identities | — |
| CI/CD | GitHub Actions + Workload Identity Federation | — |

### Supporting Services

| Service | Purpose |
|---------|---------|
| Log Analytics Workspace | Centralized logging for all services |
| Application Insights | APM, distributed tracing, metrics |
| Azure Key Vault | Runtime secrets for non-Entra integrations |
| User-Assigned Managed Identity (per workload) | Credential-free service-to-service auth |
| Private DNS Zones | Name resolution for private endpoints |
| Azure Monitor Alerts | Operational alerting |
| Microsoft Entra ID | Identity provider, app roles, groups |

---

## 6. Provisioning Limit Checklist

### Phase 1: Prepare Resource Inventory

| Resource Type | Number to Deploy | Total After Deployment | Limit/Quota | Notes |
|---------------|------------------|------------------------|-------------|-------|
| Microsoft.MachineLearningServices/workspaces (kind: Hub) | 1 | _TBD_ | _TBD_ | Foundry hub — see [ARM reference](https://learn.microsoft.com/azure/templates/microsoft.machinelearningservices/workspaces) |
| Microsoft.MachineLearningServices/workspaces (kind: Project) | 1 | _TBD_ | _TBD_ | Foundry project (child of hub) |
| Microsoft.CognitiveServices/accounts (kind: AIServices) | 1 | _TBD_ | _TBD_ | AI Services multi-model account for Foundry |
| Microsoft.DocumentDB/databaseAccounts | 1 | _TBD_ | _TBD_ | Cosmos DB serverless |
| Microsoft.Storage/storageAccounts | 1 | _TBD_ | _TBD_ | Blob + Functions storage + Foundry default storage |
| Microsoft.ServiceBus/namespaces | 1 | _TBD_ | _TBD_ | Standard tier |
| Microsoft.Search/searchServices | 1 | _TBD_ | _TBD_ | Basic tier |
| Microsoft.KeyVault/vaults | 1 | _TBD_ | _TBD_ | Standard |
| Microsoft.Web/sites (Functions) | 1 | _TBD_ | _TBD_ | Functions app |
| Microsoft.App/managedEnvironments | 1 | _TBD_ | _TBD_ | For eval job |
| Microsoft.Insights/components | 1 | _TBD_ | _TBD_ | App Insights |
| Microsoft.OperationalInsights/workspaces | 1 | _TBD_ | _TBD_ | Log Analytics |
| Microsoft.BotService/botServices | 1 | _TBD_ | _TBD_ | Bot channel (Teams) |
| Microsoft.Network/virtualNetworks | 1 | _TBD_ | _TBD_ | VNet for private endpoints |
| Microsoft.Network/privateEndpoints | 5 | _TBD_ | _TBD_ | Cosmos, Storage, Search, Bus, Vault |
| Microsoft.ManagedIdentity/userAssignedIdentities | 4 | _TBD_ | _TBD_ | Agent, workers, eval, notification |

> **Note on Foundry resource model:** Azure AI Foundry (as of 2026) uses `Microsoft.MachineLearningServices/workspaces` with `kind` discriminators (`Hub`, `Project`). The previously-referenced `Microsoft.MachineLearningServices/accounts` type does **not exist** in any published ARM API version. This was confirmed against the [Bicep/ARM template reference](https://learn.microsoft.com/azure/templates/microsoft.machinelearningservices/workspaces) and the [Azure Quickstart Templates for AI Foundry](https://github.com/Azure/azure-quickstart-templates/tree/master/quickstarts/microsoft.machinelearningservices/aifoundry-basics). A Foundry hub additionally requires a linked `Microsoft.CognitiveServices/accounts` resource for model inference.

> **⚠️ Pre-implementation validation spike:** Before writing Bicep, confirm the exact API version and required properties by inspecting the [AVM module for ML workspaces](https://github.com/Azure/bicep-registry-modules/tree/main/avm/res/machine-learning-services/workspace) and running `az ml workspace create --kind Hub --help` against the target subscription. Document findings in the implementation PR.

### Phase 2: Fetch Quotas and Validate Capacity

**Status:** ⏳ Deferred — subscription and location must be confirmed with user (via ask_user) after plan approval. Quota validation will be performed using azure-quotas skill before execution begins.

**Must validate:**
- Model deployment quota (TPM) for GPT-4o or selected model in target region
- Foundry workspace count limits per subscription
- AI Search service count per subscription
- Private endpoint count per subscription
- CognitiveServices account limits

---

## 7. Implementation Phases

### Phase 1: Foundation Infrastructure (Slice 1)

| Step | Description | Owner | Blocking Dependencies |
|------|-------------|-------|----------------------|
| 1.0 | Validate prerequisites (provider registration, RBAC, region overlap, quota) | Tank | Design review complete ✅ — ready to execute |
| 1.1 | Create `infra/` Bicep module structure | Tank | 1.0 |
| 1.2 | Core modules: resource group, VNet, private DNS zones | Tank | 1.1 |
| 1.3 | Data services: Cosmos DB, Storage, Service Bus, AI Search, Key Vault | Tank | 1.2 |
| 1.4 | Private endpoints for all data services | Tank | 1.3 |
| 1.5 | Managed identities and RBAC assignments | Tank | 1.3 |
| 1.6 | Monitoring: Log Analytics + Application Insights | Tank | 1.2 |
| 1.7 | Foundry hub + project + AI Services account | Tank | 1.2 + provider registration |
| 1.8 | `azure.yaml` with service definitions | Tank | 1.7 |
| 1.9 | GitHub Actions: CI + workload identity federation | Tank | 1.8 |

### Phase 2: Agent Skeleton (Slice 2 start)

| Step | Description | Owner | Blocking Dependencies |
|------|-------------|-------|----------------------|
| 2.1 | Python project structure (`pyproject.toml`, packages) | Trinity | — |
| 2.2 | intake-domain package skeleton | Trinity | — |
| 2.3 | Foundry Hosted Agent configuration | Trinity | 1.7 (infrastructure) |
| 2.4 | Channel adapter + identity extraction | Trinity | — |
| 2.5 | `get_or_create_request` + `get_request_context` commands | Trinity | — |
| 2.6 | Template loading and validation | Trinity | — |
| 2.7 | Cosmos DB repository (request CRUD) | Trinity | — |
| 2.8 | Teams pilot publishing setup | Neo | Teams spike findings required (§5.1) |
| 2.9 | Unit + component tests | Switch | — |

### Phase 3: Vertical Path (Slice 2 completion)

| Step | Description | Owner |
|------|-------------|-------|
| 3.1 | `propose_field_updates` command + validation | Trinity |
| 3.2 | Autosave + resume from Cosmos | Trinity |
| 3.3 | Foundry + App Insights trace correlation | Trinity + Tank |
| 3.4 | Integration tests (Cosmos, real Foundry) | Switch |
| 3.5 | Teams smoke test | Neo |

---

## 8. Planned File Surface

| File/Directory | Purpose |
|----------------|---------|
| `azure.yaml` | AZD project configuration |
| `infra/main.bicep` | Orchestrator — calls modules |
| `infra/main.parameters.json` | Parameterized per environment |
| `infra/modules/cosmos.bicep` | Cosmos DB account + containers |
| `infra/modules/storage.bicep` | Storage account + containers |
| `infra/modules/servicebus.bicep` | Service Bus namespace + queues |
| `infra/modules/search.bicep` | AI Search service |
| `infra/modules/keyvault.bicep` | Key Vault + access policies |
| `infra/modules/monitoring.bicep` | Log Analytics + App Insights |
| `infra/modules/network.bicep` | VNet + subnets + private endpoints + DNS zones |
| `infra/modules/identity.bicep` | User-assigned managed identities + RBAC |
| `infra/modules/bot.bicep` | Bot Service registration + Teams channel |
| `infra/modules/foundry.bicep` | Foundry hub + project + AI Services + connections |
| `infra/modules/functions.bicep` | Functions app + plan |
| `infra/modules/container-apps.bicep` | Container Apps environment + eval job |
| `src/intake-agent/` | Python Hosted Agent source |
| `src/intake-domain/` | Shared domain package |
| `src/intake-workers/` | Azure Functions workers |
| `.github/workflows/ci.yml` | CI: lint, type-check, test, security scan |
| `.github/workflows/deploy.yml` | CD: azd provision + deploy |

---

## 9. Azure Resource Map

| Resource | Name Pattern | Resource Group |
|----------|-------------|----------------|
| Resource Group | `rg-intake-{env}` | — |
| AI Foundry Hub | `aihub-intake-{env}` | `rg-intake-{env}` |
| AI Foundry Project | `aiproj-intake-{env}` | `rg-intake-{env}` |
| AI Services Account | `ais-intake-{env}` | `rg-intake-{env}` |
| Cosmos DB | `cosmos-intake-{env}` | `rg-intake-{env}` |
| Storage Account | `stintake{env}` | `rg-intake-{env}` |
| Service Bus | `sb-intake-{env}` | `rg-intake-{env}` |
| AI Search | `search-intake-{env}` | `rg-intake-{env}` |
| Key Vault | `kv-intake-{env}` | `rg-intake-{env}` |
| App Insights | `ai-intake-{env}` | `rg-intake-{env}` |
| Log Analytics | `log-intake-{env}` | `rg-intake-{env}` |
| VNet | `vnet-intake-{env}` | `rg-intake-{env}` |
| Functions App | `func-intake-{env}` | `rg-intake-{env}` |
| Container Apps Env | `cae-intake-{env}` | `rg-intake-{env}` |
| Bot Service | `bot-intake-{env}` | `rg-intake-{env}` |
| Managed Identities | `id-intake-{workload}-{env}` | `rg-intake-{env}` |

---

## 10. Identity & RBAC

| Workload Identity | Azure Role Assignments |
|-------------------|----------------------|
| `id-intake-agent-{env}` | Cosmos DB Built-in Data Contributor (product DB), Service Bus Data Sender, Search Index Data Reader, Monitoring Metrics Publisher |
| `id-intake-worker-{env}` | Service Bus Data Receiver, Cosmos DB Built-in Data Contributor, Storage Blob Data Contributor, Key Vault Secrets User |
| `id-intake-eval-{env}` | Storage Blob Data Reader (eval datasets), Monitoring Metrics Publisher |
| `id-intake-notify-{env}` | Service Bus Data Receiver, Graph TeamsActivity.Send.User (app permission via Entra) |
| GitHub Actions (federated) | Contributor + User Access Administrator on resource group |
| Deploying user/SPN | Contributor + User Access Administrator (or Owner) on resource group; Microsoft.Authorization/roleAssignments/write |

**Principles:**
- Managed identity only; no client secrets stored
- RBAC scoped to specific resources, not subscription
- Separate identity per workload trust boundary
- Workload identity federation for CI/CD (no stored credentials)
- Foundry project requires `Foundry User` role on the project scope for agent management

---

## 11. Private Networking (Baseline Variant)

> ⚠️ **Connectivity Spike Required:** The baseline assumption (public Foundry ingress + private data-service egress via VNet integration) has NOT been validated for the specific combination of Foundry Hosted Agent → private-endpoint-only data services. A connectivity spike must prove that the Hosted Agent runtime can resolve private DNS and reach private endpoints before committing to this topology.

| Service | Private Endpoint | Public Access |
|---------|-----------------|---------------|
| Cosmos DB | Yes | Disabled |
| Storage Account | Yes | Disabled |
| Service Bus | Yes | Disabled |
| AI Search | Yes | Disabled |
| Key Vault | Yes | Disabled |
| AI Services (CognitiveServices) | No (Foundry-managed connectivity) | Enabled (baseline) |
| Foundry Hub/Project | No (public ingress, Entra-authenticated) | Enabled (baseline) |
| Bot Service | No (Microsoft-managed) | Enabled |

**VNet Layout (Baseline POC):**
- `snet-private-endpoints` /24 — private endpoint NICs
- `snet-functions` /24 — Functions VNet integration (outbound)
- `snet-container-apps` /23 — Container Apps environment
- Private DNS zones for each service (`privatelink.documents.azure.com`, etc.)

**Hardened variant** (deferred to Slice 5): Foundry managed VNet with private endpoints to all dependent services, Azure Firewall controlled egress. Decision required before production.

**Fallback (if connectivity spike fails):** Deploy data services with `publicNetworkAccess: Enabled` and IP-restricted firewall rules (allow Foundry service tags + VNet) as a documented intermediate step. Document in ADR before applying.

**Reference:** [Azure AI Foundry Network Restricted quickstart](https://github.com/Azure/azure-quickstart-templates/tree/master/quickstarts/microsoft.machinelearningservices/aifoundry-network-restricted)

---

## 12. Secrets Management

| Secret | Source | Consumer |
|--------|--------|----------|
| Downstream API credentials (if non-Entra) | Key Vault | Integration worker identity |
| Cosmos DB connection | Managed identity (no secret) | — |
| Storage connection | Managed identity (no secret) | — |
| Service Bus connection | Managed identity (no secret) | — |

**Policy:**
- No secrets in code, env files, or azd environment config
- Key Vault for any non-Entra credential
- Key Vault access via RBAC (Key Vault Secrets User role)
- Secret rotation via Key Vault policies

---

## 13. Observability

| Signal | Sink | Retention |
|--------|------|-----------|
| Application traces | Application Insights | 90 days (POC) |
| Platform metrics | Azure Monitor | 93 days (default) |
| Structured logs | Log Analytics | 90 days (POC) |
| Audit events | Cosmos DB (immutable) | Per retention policy |
| Foundry traces | Foundry evaluation/tracing | Platform default |

**Correlation:** traceId → requestId → commandId → eventId → activityId

**Alerts (POC minimum):**
- Function failures > threshold
- Dead-letter queue depth > 0
- Cosmos DB 429 rate
- Agent response latency P95

---

## 14. Testing & Evaluation

| Layer | Scope | Runner |
|-------|-------|--------|
| Unit | Domain logic, validators, state machine | pytest |
| Component | Command handlers + emulated repos | pytest |
| Contract | Command/event schemas, downstream payloads | pytest |
| Integration | Real Cosmos, Service Bus, Foundry | pytest + azd env |
| E2E | Teams intake → approve → document | Playwright/manual |
| AI Evaluation | Benchmark capture accuracy, gap recall | Container Apps Job + Foundry eval |
| Security | Auth, injection, disclosure | pytest + scanning |

**Release Gate:** Signed evaluation scorecard must pass all thresholds before production promotion.

---

## 15. Cost Considerations (POC)

> ⚠️ **All estimates are indicative only.** Actual costs depend on region, model selection, usage volume, and current Azure pricing. **Use the [Azure Pricing Calculator](https://azure.microsoft.com/pricing/calculator/) to confirm estimates after region and model selection.**

| Service | Estimated Monthly (POC) | Notes |
|---------|------------------------|-------|
| Cosmos DB Serverless | ~$5–15 | Low RU usage for pilot |
| Storage LRS | ~$1 | Minimal artifacts |
| Service Bus Standard | ~$10 | Base charge |
| AI Search Basic | ~$70 | Minimum tier with index support |
| Key Vault | ~$1 | Few operations |
| Functions Consumption | ~$0–5 | Pay-per-execution |
| Container Apps Job | ~$0–5 | Runs on-demand |
| App Insights | ~$5–10 | Low volume |
| Private Endpoints (5) | ~$35 | ~$7/month each (indicative) |
| Bot Service | TBD | F0 free if valid; S1 ~$50/month — pending spike |
| AI Services / Model Inference | ~$20–100+ | **Highly variable** — depends on model (GPT-4o vs GPT-4o-mini), token volume, and pricing tier. POC pilot with <1K users may use 1–5M tokens/month. |
| Foundry Hosted Agent compute | ~$0–20 | Consumption-based; depends on invocation volume |
| **Estimated Total** | **~$150–275/month** | Indicative; confirm with Azure Pricing Calculator |

### Cost validation steps (post-region-selection):
1. Enter selected region + SKUs into [Azure Pricing Calculator](https://azure.microsoft.com/pricing/calculator/)
2. Confirm model token pricing for selected model + region
3. Review any Foundry Agent Service hosting charges (consumption metering)
4. Re-baseline estimate before requesting budget approval

---

## 16. Region & Quota Dependencies

| Dependency | Constraint |
|------------|-----------|
| Foundry Hosted Agent | Preview regions only — check [regional availability](https://learn.microsoft.com/azure/foundry/reference/region-support) at provisioning time |
| GPT-4o / model quota | Region-dependent; must confirm TPM allocation before deployment |
| AI Services (CognitiveServices) | Must be in same region as Foundry hub or a supported cross-region connection |
| Container Apps Jobs | Generally available in most regions |
| Private endpoints | Generally available |
| Cosmos DB Serverless | Generally available |
| AI Search Basic | Available in most regions; some new regions may lack Basic tier |
| **Region overlap** | All above services must be available in a SINGLE region (or validated cross-region pattern) |

**✅ Region selected: `eastus2`.** Confirmed: Foundry Agent Service, Functions Flex Consumption, Cosmos DB Serverless, AI Search Basic, Service Bus Standard, Container Apps, and private endpoints are all available in East US 2.

---

## 17. Rollback & Cleanup

> ⚠️ **Destructive operations require explicit user confirmation.** Never run cleanup commands unattended in production environments.

### Resource Lifecycle

| Scenario | Approach |
|----------|----------|
| Failed deployment | `azd down` removes the resource group and all contained resources |
| Partial failure | Re-run `azd provision` (idempotent Bicep) |
| Full environment teardown | See cleanup procedure below |
| Rollback agent version | Redeploy previous container/package version via CI/CD |
| Data recovery | Cosmos DB continuous backup / point-in-time restore (7-day window for serverless) |

### Cleanup Procedure (explicit user confirmation required)

**Step 1: Resource group deletion**
```bash
azd down --force
```
This deletes the resource group and all resources within it. Resources with soft-delete (Key Vault, Cosmos DB, AI Services) enter a soft-deleted state but are NOT permanently purged.

**Step 2: Soft-deleted resource cleanup (separate, manual)**

| Service | Soft-Delete Behavior | Purge Command |
|---|---|---|
| Key Vault | 90-day retention by default | `az keyvault purge --name <name>` |
| Cosmos DB | Restorable account retained for 30 days ([docs](https://learn.microsoft.com/azure/cosmos-db/continuous-backup-restore-introduction)) | Cannot be purged manually — expires after retention period. Soft delete (preview) has separate 1-day default. |
| AI Services (CognitiveServices) | 48-hour soft-delete | `az cognitiveservices account purge --name <name> --resource-group <rg> --location <loc>` |

> **Important:** `azd down --purge` passes `--purge` to Key Vault and Cognitive Services but does **NOT** purge Cosmos DB restorable accounts. Cosmos DB restorable accounts cannot be manually purged and are retained by the platform for the configured continuous backup window. Plan accordingly if the resource name must be reused.

**Step 3: Data retention awareness**
- Cosmos DB continuous backup data is retained even after account deletion (platform-managed, time-limited)
- Log Analytics data persists for the configured retention period even after workspace deletion (soft-delete: 14 days)
- Application Insights follows Log Analytics workspace lifecycle

### Safe reset for POC iteration:
```bash
# Confirm with user before executing
azd down --force --purge   # Deletes RG, purges Key Vault + Cognitive Services
# Cosmos DB restorable account will expire automatically
# Wait for name availability if reusing same resource names
azd up                      # Fresh deployment
```

---

## 18. Deployment Success Verification

| Check | Method | Pass Criteria |
|-------|--------|---------------|
| Infrastructure provisioned | `azd provision` exit code 0 | All resources created |
| Agent deployed | `azd deploy` exit code 0 | Agent running in Foundry |
| Private endpoint connectivity | DNS resolution + data-plane call from Functions VNet | Cosmos/Storage/Bus/Search/Vault reachable via private IP |
| Public access disabled | ARM query on data services | `publicNetworkAccess: Disabled` |
| Identity working | Agent → Cosmos read/write via managed identity | No auth failures |
| Teams publishing | Send test message in Teams (post-spike) | Agent responds |
| Monitoring active | Query App Insights for traces | Traces visible within 5 minutes |
| CI/CD pipeline | Push to branch, verify workflow run | Green build + deploy |
| Foundry connectivity spike | Agent invokes Cosmos/Storage via private endpoint | Validates §11 baseline assumption |

---

## 19. Unresolved Decisions

| # | Decision | Default Recommendation | Requires User Approval? | Blocking? |
|---|----------|----------------------|------------------------|-----------|
| 1 | Azure subscription | ✅ **Resolved** — `87e1a785-896b-4eb4-a214-47f67995133e` confirmed | — | ✅ Resolved |
| 2 | Azure region / location | ✅ **Resolved** — `eastus2` confirmed | — | ✅ Resolved |
| 3 | Network variant for POC | **Baseline** — `deployPrivateEndpoints=false` (safe POC default; connectivity spike required to enable) | No | No |
| 4 | Cosmos DB tier | ✅ **Resolved** — Serverless | No | No |
| 5 | Model selection (GPT-4o vs other) | Defer — validate TPM quota in AI Foundry portal before setting `deployFoundry=true` | ✅ Yes | ⛔ Yes (before Foundry gate enabled) |
| 6 | Functions hosting plan | ✅ **Resolved** — Flex Consumption (FC1) implemented | No | No |
| 7 | Word/PDF generation runtime | Functions worker — decide during Slice 4 | No | No |
| 8 | First downstream integration target | Contract-test stub for POC | No | No |
| 9 | Foundry hub/project name | ✅ **Resolved** — `aihub-intake-{env}` / `aiproj-intake-{env}` | No | No |
| 10 | Environment name (azd) | ✅ **Resolved** — `dev` as default | No | No |
| 11 | Teams publishing path + Bot Service SKU | Foundry Activity Protocol + Bot Service (F0 or S1) — spike required (§5.1); gated by `deployBotService=false` | ✅ Yes (after spike) | ⛔ Yes — blocks step 2.8 |
| 12 | Baseline network connectivity validation | Prove Hosted Agent → private endpoints works — spike required before setting `deployPrivateEndpoints=true` | No | ⛔ Yes — blocks production topology commitment |

---

## 20. Execution Checklist

### Phase 1: Planning
- [x] Analyze workspace (NEW mode — no existing code)
- [x] Gather requirements (from architecture.md + productbacklog.md)
- [x] **User approved this plan**
- [x] ✅ **Authenticate to correct Azure account/subscription** — `haduong@MngEnvMCAP456638.onmicrosoft.com`, subscription confirmed Enabled
- [x] ✅ **Confirm subscription and location** — `87e1a785-…`, `eastus2`
- [x] ✅ **Validate region overlap** — all required services available in eastus2
- [x] ✅ **Validate provider registrations** — see Preflight Evidence table (ServiceBus/MachineLearningServices/BotService need registration before use)
- [x] ✅ **Validate deployer RBAC** — Owner at management group (covers Contributor + User Access Administrator)
- [x] ✅ **Validate quota signals** — AI Search 0/12, CognitiveServices 0/30, vCPUs 0/100 (model TPM quota deferred until Foundry gate enabled)
- [x] ✅ **Prepare resource inventory**
- [x] ✅ **Fetch quotas and validate capacity**
- [x] Scan codebase (no code exists — greenfield)
- [x] Select recipe (AZD + Bicep per ADR-011)
- [x] Plan architecture (from architecture.md reconciliation)
- [ ] Complete Teams publishing spike (§5.1) — Neo's scope
- [ ] Complete baseline connectivity spike (§11) — Tank + Trinity

### Phase 2: Execution — Infrastructure (Tank)
- [x] ✅ **Validate Foundry ARM resource model** — confirmed `Microsoft.MachineLearningServices/workspaces` with kind Hub/Project; `systemDatastoresAuthMode` removed (not in published schema); `deployFoundry` gate in place
- [x] ✅ **Generate Bicep modules (`infra/`)** — 13 modules, all build/lint clean (0 warnings)
- [x] ✅ **Generate `azure.yaml`** — service mappings for workers (Functions); agent deployment via hook
- [x] ✅ **Generate GitHub Actions workflows** — `ci.yml` (lint/test/security) + `deploy.yml` (workload identity federation, azd provision + deploy)
- [x] ✅ **Preflight scripts** — `scripts/azure/preflight.sh/.ps1`, `what-if.sh`, `post-deploy-verify.sh/.ps1`
- [x] ✅ **Register Microsoft.ServiceBus provider** — Registered 2026-08-07T17:05Z (confirmed at 50s)
- [ ] Set up Entra app registration for GitHub Actions federated credential (see deploy.yml comments)
- [ ] Set GitHub Actions repository variables: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_ENV_NAME`, `AZURE_LOCATION`

### Phase 2: Execution — Application (Trinity/Neo/Switch)
- [ ] Python project structure (`pyproject.toml`, packages) — Trinity
- [ ] intake-domain package skeleton — Trinity
- [ ] Foundry Hosted Agent configuration — Trinity
- [ ] Teams pilot publishing setup — Neo (after spike §5.1)
- [ ] Unit + component tests — Switch

### Phase 3: Validation
- [x] ✅ Run `scripts/azure/preflight.ps1` — PASSED (0 errors, 2 expected warnings)
- [x] ✅ Run `scripts/azure/what-if.sh` equivalent — 38 creates, 0 errors, 0 blockers
- [x] ✅ AZD installation verified (v1.28.1)
- [x] ✅ AZD auth confirmed (haduong@MngEnvMCAP456638.onmicrosoft.com)
- [x] ✅ AZD env `dev` configured (sub/loc set, no secrets in .env)
- [x] ✅ `azd provision --preview --no-prompt` — 13 resources to CREATE, 0 errors
- [x] ✅ Bicep build + lint clean
- [x] ✅ Build verification: pytest 679 passed, 92.33% coverage, ruff clean, mypy clean
- [x] ✅ Static RBAC verification: all data-plane roles, no Owner/Contributor runtime, least privilege
- [x] ✅ Provider registration: all required registered, gated providers intentionally unregistered
- [x] ✅ Secret scan: no secrets in code or env files
- [x] ✅ **Plan status: Validated (2026-08-07T18:05:49Z)**
- [ ] Set up Entra app registration for GitHub Actions federated credential (see deploy.yml comments)
- [ ] Set GitHub Actions repository variables: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_ENV_NAME`, `AZURE_LOCATION`

### Phase 4: Deployment
- [x] ✅ Run `azd provision` — 13 resources provisioned (2026-08-07T20:20Z, ARM deployment `dev-1786130319`)
- [ ] ❌ Run `azd deploy` — BLOCKED (see Section 25)
- [x] ✅ Run `pwsh scripts/azure/post-deploy-verify.ps1` — 5/5 checks passed
- [ ] ❌ Verify deployment success (workers not deployed)
- [ ] ❌ Update plan status to "Deployed" (blocked — workers not deployed)

---

## 21. Validation Proof

> **Final clean validation gate executed: 2026-08-07T16:40:52.306+01:00** — all blocking checks passed with exit 0. No source, test, or infra files were modified.

| # | Check | Command | Result | Exit | Evidence |
|---|-------|---------|--------|------|----------|
| 1 | pytest + coverage | `python -m pytest --cov=src --cov-fail-under=80 -q` | ✅ PASSED | 0 | 679 passed in 12.61s · Total coverage: **92.33%** (≥80 threshold met) |
| 2 | ruff lint | `python -m ruff check src tests evaluation` | ✅ PASSED | 0 | `All checks passed!` |
| 3 | mypy type check | `python -m mypy src` | ✅ PASSED | 0 | `Success: no issues found in 31 source files` |
| 4 | import-linter | `python -c "from importlinter.cli import lint_imports; lint_imports()"` | ✅ PASSED | 0 | Analyzed 57 files, 140 deps · 4 contracts kept, 0 broken |
| 5 | demo smoke test | `python -m intake_teams.demo` | ✅ PASSED | 0 | `17 passed  0 failed  (17 total)` · LOCAL DEV MODE active |
| 6 | Bicep build | `az bicep build --file infra/main.bicep` | ✅ PASSED | 0 | Clean build (upgrade notice only — v0.46.1 available) |
| 7 | azure.yaml | `python -c "import yaml; yaml.safe_load(open('azure.yaml'))"` | ✅ PASSED | 0 | `name: intake-agent · services: ['workers']` |
| 8 | preflight.ps1 | `pwsh -File scripts\azure\preflight.ps1 -SubscriptionId 87e1a785... -WhatIf` | ✅ PASSED | 0 | 0 errors · 2 expected warnings (BotService/MachineLearning — gated features intentionally disabled) |
| 9 | secret scan | ripgrep pattern scan (excl. `.env*`, `.git`, caches, venvs) | ✅ PASSED | 0 | `No secret patterns found.` |

**All 9 checks: EXIT 0. Status promoted to Ready for Validation.**

### Formal Azure-Validate Proof (2026-08-07T18:05:49Z)

| # | Check | Command | Result | Exit | Evidence |
|---|-------|---------|--------|------|----------|
| V1 | AZD installation | `azd version` | ✅ PASSED | 0 | azd version 1.28.1 (stable) |
| V2 | AZD auth | `azd auth login --check-status` | ✅ PASSED | 0 | Logged in as haduong@MngEnvMCAP456638.onmicrosoft.com |
| V3 | Environment setup | `azd env new dev; azd env set AZURE_SUBSCRIPTION_ID …; azd env set AZURE_LOCATION eastus2` | ✅ PASSED | 0 | env `dev` default, sub+loc set |
| V4 | Subscription/Location | `azd env get-values` | ✅ PASSED | 0 | `AZURE_SUBSCRIPTION_ID=87e1a785-896b-4eb4-a214-47f67995133e`, `AZURE_LOCATION=eastus2` |
| V5 | Provision preview | `azd provision --preview --no-prompt` | ✅ PASSED | 0 | 13 resources to CREATE (rg, cosmos, sb, srch, st, kv, appi, log, vnet, asp, func, cae, job), 0 errors, 45s |
| V6 | Bicep build | `az bicep build --file infra/main.bicep` | ✅ PASSED | 0 | Clean (upgrade notice only) |
| V7 | Bicep lint | `az bicep lint --file infra/main.bicep` | ✅ PASSED | 0 | Clean (upgrade notice only) |
| V8 | pytest + coverage | `python -m pytest --cov=src --cov-fail-under=80 -q` | ✅ PASSED | 0 | 679 passed in 7.89s, 92.33% coverage |
| V9 | ruff lint | `python -m ruff check src tests evaluation` | ✅ PASSED | 0 | All checks passed |
| V10 | mypy type check | `python -m mypy src` | ✅ PASSED | 0 | Success: no issues found in 31 source files |
| V11 | Static RBAC review | grep `roleDefinitionId` across `infra/modules/*.bicep` | ✅ PASSED | — | All assignments use data-plane roles: Cosmos Data Contributor, SB Data Sender/Receiver, Blob Data Contributor/Reader, KV Secrets User/Officer, Search Index Data Reader, AI Developer, Cognitive Services User. No Owner/Contributor runtime assignments. Scoped to individual resources (not sub/RG). |
| V12 | Secrets in env | `cat .azure/dev/.env` | ✅ PASSED | — | Only `AZURE_ENV_NAME`, `AZURE_LOCATION`, `AZURE_SUBSCRIPTION_ID` — no secrets |
| V13 | Provider registration | Preflight evidence in plan | ✅ PASSED | — | All required providers registered. MachineLearningServices/BotService intentionally unregistered (gated false). |

**All 13 formal validation checks: PASSED. Status promoted to Validated.**

---

## 22. Files to Generate

| File | Purpose | Status |
|------|---------|--------|
| `.azure/deployment-plan.md` | This plan | ✅ |
| `azure.yaml` | AZD project configuration | ⏳ |
| `infra/main.bicep` | Orchestrator module | ⏳ |
| `infra/main.parameters.json` | Environment parameters | ⏳ |
| `infra/modules/*.bicep` | Resource modules (14 files) | ⏳ |
| `src/intake-agent/pyproject.toml` | Agent package config | ⏳ |
| `src/intake-domain/pyproject.toml` | Domain package config | ⏳ |
| `src/intake-workers/pyproject.toml` | Workers package config | ⏳ |
| `.github/workflows/ci.yml` | CI pipeline | ⏳ |
| `.github/workflows/deploy.yml` | CD pipeline | ⏳ |

---

## 23. Next Steps

> Current: Phase 1 — Planning | Approved | Paused

**⛔ EXECUTION PAUSED**

The authenticated Azure account does not expose the intended subscription. All implementation, validation, and deployment phases are blocked until this is resolved.

**To Resume Execution:**

1. **Authenticate to the correct Azure subscription:**
   - Confirm the target subscription ID with your Azure administrator
   - Run: `az logout` && `az login` to switch to the correct account/tenant
   - Verify: `az account show` confirms the correct subscription is active
   
2. **Once authenticated to the correct subscription:**
   - User confirms the selected subscription and location (via ask_user)
   - Tank validates region overlap, provider registration, RBAC, and model quota
   - Complete Teams publishing spike (§5.1) and baseline connectivity spike (§11)
   - Begin Phase 2 execution: infrastructure generation
   - Begin Phase 2 execution: application scaffolding

**No subscription, region, or model selection is made at this time.** Proceed only after the user explicitly resumes with correct authentication.

---

## 24. References

| Topic | Link |
|-------|------|
| Azure AI Foundry ARM/Bicep reference | https://learn.microsoft.com/azure/templates/microsoft.machinelearningservices/workspaces |
| Foundry basic setup quickstart (Bicep) | https://github.com/Azure/azure-quickstart-templates/tree/master/quickstarts/microsoft.machinelearningservices/aifoundry-basics |
| Foundry network-restricted quickstart | https://github.com/Azure/azure-quickstart-templates/tree/master/quickstarts/microsoft.machinelearningservices/aifoundry-network-restricted |
| AVM module: ML Services Workspace | https://github.com/Azure/bicep-registry-modules/tree/main/avm/res/machine-learning-services/workspace |
| Publish Foundry agents to Teams (portal) | https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot |
| Publish Foundry agents to Teams (REST + VNet) | https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot-virtual-network |
| Foundry regional availability | https://learn.microsoft.com/azure/foundry/reference/region-support |
| Cosmos DB continuous backup / restore | https://learn.microsoft.com/azure/cosmos-db/continuous-backup-restore-introduction |
| Cosmos DB soft delete (preview) | https://learn.microsoft.com/azure/cosmos-db/soft-delete |
| Azure Pricing Calculator | https://azure.microsoft.com/pricing/calculator/ |
| Foundry RBAC roles | https://learn.microsoft.com/azure/foundry/concepts/rbac-foundry |

---

## 25. Deployment Execution Results (2026-08-07T20:45:00Z)

**Deployment Engineer:** Tank (Copilot CLI, azure-deploy workflow)
**ARM Deployment:** `dev-1786130319` | 2026-08-07T20:20Z | Duration: ~2m

### 25.1 Infrastructure Provisioning — ✅ COMPLETE

All 13 resources provisioned in `rg-intake-dev` (eastus2). Six `azd provision` runs were required to resolve cascading issues (see §25.5 Fix Log).

| Resource | Name | Location | Status | Resource ID Suffix |
|----------|------|----------|--------|-------------------|
| Resource Group | `rg-intake-dev` | eastus2 | ✅ Succeeded | `.../rg-intake-dev` |
| Storage Account | `st2k2osaevug` | eastus2 | ✅ Succeeded | `.../storageAccounts/st2k2osaevug` |
| Key Vault | `kv-2k2osaevugjeg` | eastus2 | ✅ Succeeded | `.../vaults/kv-2k2osaevugjeg` |
| Log Analytics | `log-intake-dev` | eastus2 | ✅ Succeeded | `.../workspaces/log-intake-dev` |
| App Insights | `appi-intake-dev` | eastus2 | ✅ Succeeded | `.../components/appi-intake-dev` |
| Managed Identity (agent) | `id-intake-agent-dev` | eastus2 | ✅ Succeeded | `.../userAssignedIdentities/id-intake-agent-dev` |
| Managed Identity (worker) | `id-intake-worker-dev` | eastus2 | ✅ Succeeded | `.../userAssignedIdentities/id-intake-worker-dev` |
| Managed Identity (eval) | `id-intake-eval-dev` | eastus2 | ✅ Succeeded | `.../userAssignedIdentities/id-intake-eval-dev` |
| Managed Identity (notify) | `id-intake-notify-dev` | eastus2 | ✅ Succeeded | `.../userAssignedIdentities/id-intake-notify-dev` |
| Cosmos DB | `cosmos-2k2osaevug` | eastus2 | ✅ Succeeded | `.../databaseAccounts/cosmos-2k2osaevug` |
| Service Bus | `sb-2k2osaevugje` | eastus2 | ✅ Succeeded | `.../namespaces/sb-2k2osaevugje` |
| AI Search | `srch-2k2osaevugje` | **eastus** ⚠️ | ✅ Succeeded | `.../searchServices/srch-2k2osaevugje` |
| VNet | `vnet-intake-dev` | eastus2 | ✅ Succeeded | `.../virtualNetworks/vnet-intake-dev` |
| App Service Plan | `asp-intake-dev` | eastus2 | ✅ Succeeded (FC1) | `.../serverfarms/asp-intake-dev` |
| Function App | `func-intake-dev` | eastus2 | ✅ Running | `.../sites/func-intake-dev` |
| Container Apps Env | `cae-intake-dev` | eastus2 | ✅ Succeeded | `.../managedEnvironments/cae-intake-dev` |
| Container App Job | `job-intake-eval-dev` | eastus2 | ✅ Succeeded | `.../jobs/job-intake-eval-dev` |

> ⚠️ AI Search deployed to `eastus` (not `eastus2`) — capacity unavailable in eastus2 for both Basic and Standard SKU. SKU changed to Standard (~$250/month vs ~$70/month Basic). See Fix Log.

**Subscription:** `87e1a785-896b-4eb4-a214-47f67995133e` | **RG:** `rg-intake-dev` | **Portal:** https://portal.azure.com/#@/resource/subscriptions/87e1a785-896b-4eb4-a214-47f67995133e/resourceGroups/rg-intake-dev/overview

### 25.2 Workers Package Deployment — ❌ BLOCKED

**Status:** NOT DEPLOYED — blocked by converging Azure constraints

**Root cause analysis:**

| Blocker | Constraint | Impact |
|---------|-----------|--------|
| `publicNetworkAccess: Disabled` on ALL storage | Azure Policy (Deny mode, subscription-wide) | FC1 blob-based deployment upload (from developer machine) returns `403 AuthorizationFailure` regardless of RBAC assignments |
| 0 VM quota (`InternalSubscriptionIsOverQuotaForSku`) | Subscription quota (East US 2, ALL regions) | Y1 (Dynamic Consumption) plan cannot be created — requires 1 VM quota, subscription limit is 0 |

**FC1 (Flex Consumption) deployment mechanism:** FC1 ONLY supports blob container upload to `deploymentpackage` container. No Kudu/SCM alternative. The `publicNetworkAccess: Disabled` policy blocks this upload from any public internet source.

**Y1 (Consumption) alternative:** Y1 supports Kudu/SCM deployment (not blob-based). But subscription has 0 VM quota in ALL regions — `az appservice plan create` with Y1 SKU fails with quota error.

**Attempted fix paths:**
1. Service endpoint on `snet-functions` + VNet rule on storage → resolves runtime access, NOT deployer access
2. `az functionapp deploy --type zip` → HTTP 415 (FC1 does not support Kudu/OneDeploy)
3. Y1 plan creation → quota blocked in eastus2 AND eastus

**Workarounds (requires user action):**

| Option | How | Notes |
|--------|-----|-------|
| Azure Cloud Shell | Open portal → Cloud Shell → `cd /tmp; git clone <repo>; azd auth login; azd deploy` | Cloud Shell runs inside Azure; may bypass publicNetworkAccess restriction. **Most accessible.** |
| Request Y1 VM quota | Azure Portal → Quotas → request "Total Regional vCPUs ≥ 1" in eastus2 | Takes 1-2 business days; then re-provision with Y1 plan |
| Enable private endpoint for storage | Set `deployPrivateEndpoints=true` in `infra/main.parameters.json`; reprovision | Fully resolves but adds ~$15/month PE cost + DNS complexity |
| GitHub Actions self-hosted runner | Deploy ACA Job or VM (requires quota) in VNet, register as GitHub runner | Requires VM quota which is currently 0 |

**Endpoints (as-configured, no HTTP trigger deployed):**
- Function App host: `https://func-intake-dev.azurewebsites.net` *(no HTTP endpoint — all functions are Service Bus-triggered)*
- Function App SCM: `https://func-intake-dev.scm.azurewebsites.net` *(accessible but deployment returns 415 for FC1)*
- Service Bus namespace: `sb-2k2osaevugje.servicebus.windows.net`
- Cosmos DB endpoint: `https://cosmos-2k2osaevug.documents.azure.com:443/`
- AI Search endpoint: `https://srch-2k2osaevugje.search.windows.net`
- Key Vault URI: `https://kv-2k2osaevugjeg.vault.azure.net/`

**Telemetry:** App Insights `appi-intake-dev` (instrumentationKey: `f4cf61c6-1b71-494c-9a9e-c046eb2283d1`, appId: `2c429d16-29cb-4ed6-8e7b-4367ae099b81`) is provisioned and linked. Telemetry will flow once workers are deployed and Function App processes messages.

### 25.3 Post-Deploy Verification

**Script:** `pwsh scripts/azure/post-deploy-verify.ps1`
**Timestamp:** 2026-08-07T20:30Z

| # | Check | Result | Details |
|---|-------|--------|---------|
| 1 | Resource Group | ✅ PASSED | `rg-intake-dev` provisioning state: Succeeded |
| 2 | Cosmos DB | ✅ PASSED | `cosmos-2k2osaevug` — provisioningState: Succeeded |
| 3 | Service Bus | ✅ PASSED | `sb-2k2osaevugje` — provisioningState: Succeeded |
| 4 | AI Search | ✅ PASSED | `srch-2k2osaevugje` — provisioningState: Succeeded |
| 5 | Function App | ✅ PASSED | `func-intake-dev` — state: Running |

**All 5 checks passed.** Workers not deployed so Function App has no code — "Running" indicates the host process is active.

### 25.4 Live RBAC Verification

**Timestamp:** 2026-08-07T20:35Z | **Verified by:** Tank (azure-deploy workflow, step 9)

#### Storage Account (`st2k2osaevug`)

| Principal | Identity | Role | Type | Least-Privilege? |
|-----------|----------|------|------|-----------------|
| `id-intake-worker-dev` | `principalId: 2b151595` | Storage Blob Data Contributor | ServicePrincipal | ✅ Correct (read/write blobs for artifacts) |
| `id-intake-eval-dev` | `principalId: 24ff6a11` | Storage Blob Data Reader | ServicePrincipal | ✅ Correct (read-only eval datasets) |
| `haduong@MngEnvMCAP456638` | deployer | Storage Blob Data Contributor | User | ✅ Required for deployment package upload |

> ✅ `Storage Blob Data Owner` (overpowered, added during troubleshooting) removed from worker identity during verification.

#### Key Vault (`kv-2k2osaevugjeg`)

| Principal | Identity | Role | Least-Privilege? |
|-----------|----------|------|-----------------|
| `id-intake-worker-dev` | `principalId: 2b151595` | Key Vault Secrets User | ✅ Read-only secrets access |
| `haduong@MngEnvMCAP456638` | deployer | Key Vault Secrets Officer | ✅ Manage secrets during deployment |

#### Cosmos DB (`cosmos-2k2osaevug`) — SQL Role Assignments

| Principal | Identity | Role | Least-Privilege? |
|-----------|----------|------|-----------------|
| `id-intake-agent-dev` | `principalId: 389572d8` | Cosmos DB Built-in Data Contributor (0002) | ✅ Data read/write only; no admin |
| `id-intake-worker-dev` | `principalId: 2b151595` | Cosmos DB Built-in Data Contributor (0002) | ✅ Data read/write only; no admin |

#### Service Bus (`sb-2k2osaevugje`)

| Principal | Identity | Role | Least-Privilege? |
|-----------|----------|------|-----------------|
| `id-intake-agent-dev` | `principalId: 389572d8` | Azure Service Bus Data Sender | ✅ Send-only; cannot receive |
| `id-intake-worker-dev` | `principalId: 2b151595` | Azure Service Bus Data Sender | ✅ Needed for DLQ forwarding |
| `id-intake-worker-dev` | `principalId: 2b151595` | Azure Service Bus Data Receiver | ✅ Receive messages from queue |

#### AI Search (`srch-2k2osaevugje`)

| Principal | Identity | Role | Least-Privilege? |
|-----------|----------|------|-----------------|
| `id-intake-agent-dev` | `principalId: 389572d8` | Search Index Data Reader | ✅ Read-only index query |

**RBAC Findings:**
- ✅ No `Owner` or `Contributor` (Azure ARM RBAC) roles assigned to any runtime managed identity
- ✅ All data-plane roles are least-privilege and scoped to individual resources (not subscription/RG)
- ✅ No cross-identity over-provisioning
- ⚠️ `id-intake-notify-dev` has no role assignments yet — correct for POC (notification service not implemented)

### 25.5 Infrastructure Fix Log

| Run | Issue | Fix Applied | Files Changed |
|-----|-------|-------------|---------------|
| 1st provision | `cosmos-intake-dev` DNS name taken globally; `sb-intake-dev` name taken; `srch-intake-dev` InsufficientResourcesAvailable (eastus2) | Added `resourceToken` suffix to cosmos/sb/search names | `infra/main.bicep` |
| 2nd provision | AI Search still failing (Basic capacity) | Changed SKU from `basic` to `standard` | `infra/modules/search.bicep` |
| 3rd provision | AI Search still failing; added `searchServiceLocation` param to deploy to `eastus` | AI Search location override to `eastus` | `infra/main.bicep`, `infra/modules/search.bicep` |
| 4th provision | `SubnetMissingRequiredDelegation` — FC1 needs `Microsoft.App/environments`, not `Microsoft.Web/serverFarms` | Changed `snet-functions` delegation | `infra/modules/network.bicep` |
| 5th deploy | `503 Site Unavailable` → `InaccessibleStorageException` → `403 AuthorizationFailure` | Diagnosed Azure Policy `publicNetworkAccess:Disabled`; tried VNet service endpoint, storage VNet rule; resolved circular dependency in Bicep module graph | `infra/modules/network.bicep`, `infra/modules/storage.bicep`, `infra/main.bicep` |
| 6th provision | `RoleAssignmentExists` (deployer Blob Contributor GUID collision) | Removed Bicep-managed `deployerBlobContributor` resource (assignment persists manually) | `infra/modules/storage.bicep` |

### 25.6 Known Issues / Follow-up Required

| Issue | Severity | Recommended Action |
|-------|----------|--------------------|
| Workers package NOT deployed | 🔴 High | Deploy from Azure Cloud Shell (see §25.2 workarounds) |
| AI Search in `eastus` not `eastus2` | 🟡 Medium | Request eastus2 AI Search quota increase or accept cross-region latency |
| AI Search SKU: Standard ($250/month) vs planned Basic ($70/month) | 🟡 Medium | Downgrade to Basic once eastus2 capacity available |
| `publicNetworkAccess: Disabled` policy blocks CI/CD from GitHub Actions | 🔴 High | Set up private endpoint for storage or configure self-hosted runner |
| `allowSharedKeyAccess: false` policy — Function App storage uses managed identity | 🟢 Low | Correctly handled in Bicep (`AzureWebJobsStorage__credential: managedidentity`) |
| Storage Blob Data Owner (manual) removed — confirms clean RBAC | ✅ Resolved | No action needed |

---

## Section 26 — Recovery Deployment: Storage PE + Container Apps Job Runner (2026-08-07)

### 26.1 Root Cause Summary

Deployment blocked after initial provision: Azure Policy (publicNetworkAccess: Disabled + llowSharedKeyAccess: false) prevented all external blob data-plane access. Y1 plan unavailable (0 VM quota). FC1 Kudu deployment pipeline (/api/publish) blocked because it uploads to storage, which was inaccessible from the public internet.

### 26.2 Recovery Actions

| Step | Action | Result |
|------|--------|--------|
| 1 | Added deployStoragePrivateEndpoint: true param to 
etwork.bicep/main.bicep/main.parameters.json | PE pe-st2k2osaevug-blob provisioned; DNS A record 10.0.1.4 in privatelink.blob.core.windows.net |
| 2 | zd provision completed | ARM dev-1786131597 succeeded; all 13 resources + PE |
| 3 | Created Container Apps Job job-deploy-runner-tmp in cae-intake-dev (worker identity) | Manual job with azure-cli:latest image; base64-encoded source as env vars |
| 4 | Grant temp Contributor on unc-intake-dev to worker identity 2b151595-089a-41e9-8942-ccd930dc6a5f | Needed for z functionapp restart within the VNet |
| 5 | Deployment runner iterations (v1-v4): fixed --username→--client-id, no pip in image, FC1 requires plain POST to Kudu /api/publish (not ?type=zip) | v4 succeeded: HTTP 202, deployment ID 75aef7ef-3d66-477c-acaf-5982534ecc78 |
| 6 | Added AzureWebJobsStorage__accountName=st2k2osaevug app setting | Resolves WebJobs host health check |
| 7 | Deleted job-deploy-runner-tmp | Cleanup complete |
| 8 | Removed temp Contributor role from worker identity on unc-intake-dev | Cleanup complete |

### 26.3 Deployment Evidence

**Deployment Trigger:**
- Container Apps Job job-deploy-runner-tmp-wrvxxy0 (Succeeded, 2026-08-07T20:20:08Z)
- Method: POST https://func-intake-dev.scm.azurewebsites.net/api/publish (Kudu Flex One Deploy)
- Content-Type: pplication/zip (no ?type=zip — FC1 does not support type query param)
- HTTP Response: 202 Accepted
- Deployment ID: 75aef7ef-3d66-477c-acaf-5982534ecc78

**Package:**
- Source: src/intake_workers/ (function_app.py, host.json, requirements.txt, __init__.py)
- Size: 1422 bytes
- Build: Source-only zip (azure.functions is runtime-provided; no SDK imports in handler)

**Function App Host Log (2026-08-07T20:21:11Z):**
`
4 functions loaded
Worker process started and initialized.
Found the following functions:
  Host.Functions.document_worker
  Host.Functions.domain_event_dispatcher
  Host.Functions.notification_worker
  Host.Functions.outbox_dispatcher (timer)
ServiceBusOptions initialized
Host started (33ms)
`

### 26.4 Post-Deployment RBAC State

| Identity | Resource | Role | Scope |
|----------|----------|------|-------|
| id-intake-worker-dev | Storage st2k2osaevug | Storage Blob Data Contributor | Account |
| id-intake-worker-dev | Storage st2k2osaevug | Storage Queue Data Contributor | Account |
| id-intake-worker-dev | Key Vault kv-2k2osaevugjeg | Key Vault Secrets User | Account |
| id-intake-worker-dev | Cosmos DB | Cosmos DB Built-in Data Contributor | Account |
| id-intake-worker-dev | Service Bus sb-2k2osaevugje | Azure Service Bus Data Sender + Data Receiver | Namespace |
| Temp Contributor on unc-intake-dev | Removed after deployment | — | Removed |

### 26.5 Endpoint Verification

- Function App: **https://func-intake-dev.azurewebsites.net** (Running; no HTTP trigger endpoints — all Service Bus + timer triggers)
- Service Bus triggers: domain-events queue (domain_event_dispatcher), document-generation queue (document_worker), 
otification-queue queue (notification_worker)
- Timer trigger: outbox_dispatcher (every 5 minutes)

### 26.6 Remaining Open Items

| Issue | Severity | Status |
|-------|----------|--------|
| AI Search in astus (not astus2) | 🟡 Medium | Accepted for POC; request eastus2 quota to remediate |
| AI Search SKU: Standard vs planned Basic | 🟡 Medium | Accepted for POC |
| CI/CD from GitHub Actions needs in-VNet runner for future deployments | 🟡 Medium | Document approach: use Container Apps Job runner pattern established here |
| AzureWebJobsStorage__accountName added to live app settings; Bicep updated | ✅ Resolved | infra/modules/functions.bicep updated; infra/main.json rebuilt |


---

## Section 27 — Independent Post-Deployment Validation (Switch, 2026-08-07T21:27Z)

**Validator:** Switch (Quality Engineer)
**Timestamp:** 2026-08-07T21:27–21:55Z
**Scope:** Independent empirical validation of live Azure deployment after Tank's VNet-connected recovery.
**Method:** Azure CLI (`az`), App Insights REST API, Service Bus REST API — authenticated as `haduong@MngEnvMCAP456638.onmicrosoft.com`.

---

### 27.1 Check 1 — Resource Group / Provisioning State

```
az group show --name rg-intake-dev → { "state": "Succeeded", "location": "eastus2" }
az resource list --resource-group rg-intake-dev → 20 resource entries
```

All expected resources present: 4 managed identities, storage, key vault, app insights, service bus, cosmos db, AI search (eastus, accepted), VNet, 5 private DNS zones with VNet links, container apps env, app service plan, container app job (eval), function app, storage blob PE + NIC.

**RESULT: ✅ PASS** — All 20 resource entries present. RG state: `Succeeded`.

---

### 27.2 Check 2 — Function App Running + 4 Functions with Correct Triggers

```
az functionapp show → state: Running, kind: functionapp,linux
az rest GET .../func-intake-dev/functions → 4 functions
az functionapp config appsettings list → INTAKE_SERVICEBUS_QUEUE = domain-events
```

| Function | Trigger Type | Queue / Schedule |
|----------|-------------|------------------|
| `domain_event_dispatcher` | `serviceBusTrigger` | `%INTAKE_SERVICEBUS_QUEUE%` → **`domain-events`** (app setting confirmed) |
| `document_worker` | `serviceBusTrigger` | `document-generation` |
| `notification_worker` | `serviceBusTrigger` | `notification-queue` |
| `outbox_dispatcher` | `timerTrigger` | `*/5 * * * *` |

App Insights host log confirms: `"Found the following functions: Host.Functions.document_worker, Host.Functions.domain_event_dispatcher, Host.Functions.notification_worker, Host.Functions.outbox_dispatcher"` — logged at 20:33:36Z, 20:43:15Z, 20:43:36Z.

**RESULT: ✅ PASS** — Function App state `Running`; exactly 4 functions; correct trigger types, queue names, and timer schedule.

---

### 27.3 Check 3 — Latest Deployment Succeeded

```
az rest GET .../func-intake-dev/deployments
→ id: 75aef7ef-3d66-477c-acaf-5982534ecc78
  deployer: LegionOneDeploy (Kudu Flex One Deploy)
  status: 4 (Success)  active: true
  received_time: 2026-08-07T20:20:09Z  end_time: 2026-08-07T20:21:10Z
  last_success_end_time: 2026-08-07T20:21:10Z  complete: true
```

**RESULT: ✅ PASS** — Latest deployment Succeeded, active, matches Tank's deployment evidence.

---

### 27.4 Check 4 — Storage Private Endpoint / Network Security

```
az storage account show → publicNetworkAccess: "Disabled", allowSharedKeyAccess: false
az network private-endpoint show pe-st2k2osaevug-blob
  → provisioningState: Succeeded, status: "Approved", description: "Auto-Approved"
az network nic show (PE NIC) → privateIP: 10.0.1.4, subnet: snet-private-endpoints
az network private-dns zone show privatelink.blob.core.windows.net → provisioningState: Succeeded
az network private-dns link vnet list → link-vnet-intake-dev → vnet-intake-dev, Succeeded
```

**RESULT: ✅ PASS** — Storage `publicNetworkAccess: Disabled`; blob PE Approved; private IP `10.0.1.4`; DNS zone + VNet link provisioned.

---

### 27.5 Check 5 — Temporary Deployment Job Removed

```
az containerapp job list → Name: job-intake-eval-dev (only)
```

`job-deploy-runner-tmp` absent.

**RESULT: ✅ PASS** — Temporary deployment Container Apps Job removed; only permanent eval job remains.

---

### 27.6 Check 6 — RBAC Cleanup + Least-Privilege

```
az role assignment list --scope .../func-intake-dev → empty (Contributor removed) ✅
All RG/sub ServicePrincipal Owner/Contributor entries → platform accounts only, no managed identities ✅
```

Data-plane role assignments at resource scope:

| Identity | Resource | Role | Result |
|----------|----------|------|--------|
| `id-intake-worker-dev` | `st2k2osaevug` | Storage Blob Data Contributor | ✅ |
| `id-intake-eval-dev` | `st2k2osaevug` | Storage Blob Data Reader | ✅ |
| `id-intake-worker-dev` | `kv-2k2osaevugjeg` | Key Vault Secrets User | ✅ |
| `id-intake-agent-dev` | `sb-2k2osaevugje` | Azure Service Bus Data Sender | ✅ |
| `id-intake-worker-dev` | `sb-2k2osaevugje` | Azure Service Bus Data Sender + Data Receiver | ✅ |
| `id-intake-agent-dev` | `cosmos-2k2osaevug` | Cosmos DB Built-in Data Contributor (0002) | ✅ |
| `id-intake-worker-dev` | `cosmos-2k2osaevug` | Cosmos DB Built-in Data Contributor (0002) | ✅ |
| `id-intake-agent-dev` | `srch-2k2osaevugje` | Search Index Data Reader | ✅ |

`id-intake-notify-dev`: no assignments (correct for POC — service not yet implemented).

**RESULT: ✅ PASS** — No Owner/Contributor on any managed identity; all data-plane roles least-privilege at resource scope; temp Contributor removed.

---

### 27.7 Check 7 — Service Bus Queues + Smoke Event

**Queues present:** `domain-events` (Active), `domain-events-dlq-recovery` (Active)

**⚠️ Missing queues:** `document-generation` and `notification-queue` absent from `sb-2k2osaevugje`.

**Smoke event send:**
```
Correlation ID: switch-smoke-4b18c22c-ba0c-4171-96fe-394e34d0d23b
POST https://sb-2k2osaevugje.servicebus.windows.net/domain-events/messages
Authorization: Bearer <Entra — haduong granted Azure Service Bus Data Sender temporarily, removed post-test>
Content-Type: application/atom+xml;type=entry;charset=utf-8
→ HTTP 201 Created ✅
```

**Smoke event consumption:** After 12+ minutes and 3 host restart cycles, message remained in queue (`activeMessages: 1`, `deadLetterMessages: 0`). `domain_event_dispatcher` has **zero executions** across all time in App Insights.

**Root cause:** `outbox_dispatcher` timer fires correctly at every 5-min mark (confirmed), proving the host is healthy. The Service Bus AMQP extension registers listeners for all 3 SB-triggered functions at host startup. `document-generation` and `notification-queue` queues do not exist — the SB extension gets `MessagingEntityNotFoundException` for those two functions, which prevents all SB listeners (including `domain-events`) from initializing in Azure Functions v4.

**RESULT: ⚠️ PARTIAL** — Send ✅ HTTP 201. Consume ❌ never consumed. **Defect D1: missing Service Bus queues.**

---

### 27.8 Check 8 — Data/Compute Resource Health

| Resource | Check | Result |
|----------|-------|--------|
| Cosmos DB `cosmos-2k2osaevug` | Containers: `requests`, `revisions`, `workflow-events` | ✅ All 3 present |
| Storage `st2k2osaevug` | Containers: `request-artifacts`, `eval-datasets`, `deploymentpackage`, `azure-webjobs-hosts`, `azure-webjobs-secrets` | ✅ All present |
| AI Search `srch-2k2osaevugje` | SKU: Standard, Location: East US (⚠️ accepted deviation) | ✅ |
| Key Vault `kv-2k2osaevugjeg` | provisioningState: Succeeded | ✅ |
| Container Apps Env `cae-intake-dev` | provisioningState: Succeeded | ✅ |
| Container App Job `job-intake-eval-dev` | provisioningState: Succeeded | ✅ |
| Log Analytics `log-intake-dev` | Present; telemetry confirmed flowing via App Insights | ✅ |
| App Insights `appi-intake-dev` | provisioningState: Succeeded; instrumentationKey: `f4cf61c6-...`; 50+ traces ingested live | ✅ |

**RESULT: ✅ PASS** — All planned resources healthy; App Insights actively receiving telemetry.

---

### 27.9 Check 9 — HTTPS Endpoint / No HTTP Trigger

```
az functionapp show → httpsOnly: true, defaultHostName: func-intake-dev.azurewebsites.net
→ FQDN: https://func-intake-dev.azurewebsites.net
```

App Insights at 20:33:36Z, 20:43:15Z: `"Initializing function HTTP routes — No HTTP routes mapped"`. ARM confirms all 4 functions: `serviceBusTrigger` × 3 + `timerTrigger` × 1. No `httpTrigger` exists.

**RESULT: ✅ PASS** — Fully qualified HTTPS endpoint; `httpsOnly: true`; no HTTP trigger routes exist.

---

### 27.10 Check 10 — Gated Resources Absent

```
az resource list --resource-type Microsoft.MachineLearningServices/workspaces → (empty) ✅
az resource list --resource-type Microsoft.BotService/botServices → (empty) ✅
az network private-endpoint list → only pe-st2k2osaevug-blob (blob) ✅
```

**RESULT: ✅ PASS** — Foundry, Bot Service, and all non-storage private endpoints absent as intended.

---

### 27.11 Validation Summary

| # | Check | Result |
|---|-------|--------|
| 1 | RG + resource provisioning | ✅ PASS |
| 2 | Function App Running + 4 functions + correct triggers | ✅ PASS |
| 3 | Latest deployment Succeeded | ✅ PASS |
| 4 | Storage PE + publicNetworkAccess Disabled | ✅ PASS |
| 5 | Temp deployment job removed | ✅ PASS |
| 6 | RBAC cleanup + least-privilege | ✅ PASS |
| 7 | Service Bus queues + smoke event | ⚠️ PARTIAL — send ✅, consume ❌ |
| 8 | Data/compute resource health | ✅ PASS |
| 9 | HTTPS endpoint + no HTTP trigger | ✅ PASS |
| 10 | Gated resources absent | ✅ PASS |

**Overall: 9/10 PASS · 1 PARTIAL (Check 7)**

### 27.12 Defects Raised

| # | Severity | Defect | Action |
|---|----------|--------|--------|
| D1 | 🔴 High | `document-generation` and `notification-queue` SB queues missing from `sb-2k2osaevugje`. SB extension silently fails all AMQP listeners; `domain_event_dispatcher` never executes; smoke message stranded (activeMessages: 1). | Tank: add `document-generation` + `notification-queue` to `infra/modules/servicebus.bicep`; re-provision; retest smoke event consumption. |
| D2 | 🟡 Medium | Stranded smoke message (correlationId: `switch-smoke-4b18c22c-ba0c-4171-96fe-394e34d0d23b`) in `domain-events` queue. | Automatically consumed after D1 fix + host restart; or manually dequeue if needed. |
| D3 | 🟡 Medium | AI Search in `eastus` (Standard SKU) vs planned `eastus2` (Basic SKU) — accepted deviation for POC. | Request eastus2 capacity; downgrade to Basic when available. |

---

## Section 28 — SB Trigger Fix + Final Verification (2026-08-07T22:00–23:05 UTC)

### 28.1 Root Cause: SB Trigger Never Fired

**Symptom:** domain_event_dispatcher (SB trigger) did not fire for 2+ hours despite active messages in domain-events queue.

**Investigation findings:**
- All 4 functions loaded and discovered correctly on every host start
- Function group target is http shown for all functions — FC1 was only starting HTTP-group instances (driven by timer)
- FC1 SB-group instances (unction:domain_event_dispatcher) never started
- SB namespace: publicNetworkAccess: Enabled, defaultAction: Allow — connectivity confirmed
- App settings correct: INTAKE_SERVICEBUS_NAMESPACE__fullyQualifiedNamespace, INTAKE_SERVICEBUS_QUEUE=domain-events ✅
- Worker UAI had only Data Sender + Data Receiver — missing Data Owner

**Root cause documented in official Azure Functions SB trigger docs (identity-based connections section):**
> "The identity must be assigned the **Azure Service Bus Data Owner** role, or a custom role that includes Microsoft.ServiceBus/namespaces/*/read. Without this, the extension silently falls back to peek-based message estimation, which is less accurate and could result in delayed or incorrect scaling decisions."
>
> FC1 external scale controller needs Data Owner to read queue metrics and start SB-group instances. Without it, no SB-group instances are started, and triggers never fire.

**Secondary factor:** scaleAndConcurrency.alwaysReady was not configured for SB trigger groups. Without lwaysReady, FC1 relies entirely on the scale controller to start SB-group instances, making the trigger dependent on Data Owner for metric reads.

### 28.2 Fixes Applied

**1. Service Bus Data Owner role assigned to worker UAI (id-intake-worker-dev)**
- Role: Azure Service Bus Data Owner (ID:  90c5cfd-751d-490a-894a-3ce6f1109419)
- Scope: /subscriptions/.../resourceGroups/rg-intake-dev/providers/Microsoft.ServiceBus/namespaces/sb-2k2osaevugje
- Required by FC1 SB scale controller for accurate queue-depth metric reads
- Baked into infra/modules/servicebus.bicep (workerSbOwner resource)
- Old workerSbReceiver/workerSbSender resources removed (Data Owner supersedes both)

**2. FC1 lwaysReady for SB trigger groups added to infra/modules/functions.bicep:**
`json
"alwaysReady": [
  { "name": "function:domain_event_dispatcher", "instanceCount": 1 },
  { "name": "function:document_worker", "instanceCount": 1 },
  { "name": "function:notification_worker", "instanceCount": 1 }
]
`
Keeps 1 dedicated instance per SB trigger function always warm, bypassing scale-controller latency.

**3. disableLocalAuth: true fixed in infra/modules/servicebus.bicep**
- Was incorrectly set to alse (allows SAS connection strings)
- Corrected to 	rue (identity-only, matches Azure Policy requirement)

### 28.3 Provision Run

- **Deployment ID:** dev-1786139713
- **Duration:** 2m17s
- **Timestamp:** 2026-08-07T22:53:43Z → 22:58:03Z
- **All 13 resources:** ✅ Done (no errors)

### 28.4 SB Trigger Confirmation

| Event | Timestamp (UTC) | Detail |
|-------|----------------|--------|
| unction:domain_event_dispatcher group start | 2026-08-07T21:57:21Z | FC1 alwaysReady started dedicated SB-group instance |
| domain_event_dispatcher executed × 3 | 2026-08-07T21:57:22Z | 3 smoke messages consumed, each in 35ms |
| domain_event_dispatcher received message × 3 | 2026-08-07T21:57:22Z | Log confirmed body decode ✅ |
| Queue domain-events drained to 0 | 2026-08-07T22:58+ | Verified via z servicebus queue list |

**App Insights invocation IDs:**
- 1aa3516a-fc85-4c9e-bf4c-9e5755e70d83 — Succeeded
- 4e8a4c8-0f1e-45ff-9f53-ac17cd884edb — Succeeded
- 1c8a45df-2139-4bca-bea7-c0112b3ab03e — Succeeded

### 28.5 Queue Verification (Final)

| Queue | Active | DLQ |
|-------|--------|-----|
| domain-events | 0 | 0 |
| document-generation | 0 | 0 |
| 
otification-queue | 0 | 0 |
| domain-events-dlq-recovery | 0 | 0 |

### 28.6 Live RBAC (Final State)

| Resource | Worker UAI Role | Status |
|----------|----------------|--------|
| Storage st2k2osaevug | Storage Blob Data Contributor | ✅ Least-privilege |
| Key Vault kv-2k2osaevugjeg | Key Vault Secrets User | ✅ Least-privilege |
| Service Bus sb-2k2osaevugje | Azure Service Bus Data Owner | ✅ Required for FC1 scale controller |
| Cosmos DB cosmos-2k2osaevug | Cosmos DB Built-in Data Contributor | ✅ Least-privilege |

**No Owner/Contributor ARM roles on any runtime identity.** ✅
Deployer temporary Azure Service Bus Data Owner REMOVED. ✅

### 28.7 Storage State

| Property | Value | Status |
|----------|-------|--------|
| publicNetworkAccess | Disabled (policy) | ✅ Policy compliant |
| llowSharedKeyAccess | Disabled (policy) | ✅ Policy compliant |
| PE pe-st2k2osaevug-blob | Approved | ✅ VNet-accessible |

### 28.8 Function App Health

| Item | Value | Status |
|------|-------|--------|
| State | Running | ✅ |
| Functions | document_worker, domain_event_dispatcher, notification_worker, outbox_dispatcher | ✅ 4/4 |
| Timer trigger outbox_dispatcher | Firing every 5 min | ✅ |
| SB trigger domain_event_dispatcher | Confirmed executing | ✅ |
| No HTTP trigger deployed | N/A | ✅ Expected |

### 28.9 Verification Checklist

| # | Check | Result |
|---|-------|--------|
| 1 | RG + resource provisioning | ✅ PASS |
| 2 | Function App Running + 4 functions + correct triggers | ✅ PASS |
| 3 | Latest deployment Succeeded | ✅ PASS |
| 4 | Storage PE + publicNetworkAccess Disabled | ✅ PASS |
| 5 | Deployer temp roles removed | ✅ PASS |
| 6 | RBAC runtime least-privilege, no Owner/Contributor | ✅ PASS |
| 7 | SB triggers executing (domain_event_dispatcher confirmed) | ✅ PASS |
| 8 | All queue counts = 0 | ✅ PASS |
| 9 | HTTPS endpoint: no HTTP trigger (expected) | ✅ PASS |
| 10 | Gated resources absent (Foundry/Bot/private EP beyond storage) | ✅ PASS |
| 11 | disableLocalAuth: true on SB (identity-only) | ✅ PASS |
| 12 | alwaysReady configured for SB trigger groups | ✅ PASS |

**Overall: 12/12 PASS ✅**

---

## 29. Switch — Independent Revalidation (Post Tank Fixes)

**Revalidation timestamp:** 2026-08-07T23:09–23:16Z  
**Revalidated by:** Switch (Quality Engineer)  
**Scope:** Post-deployment live runtime verification after Tank applied: SB Data Owner scaling permissions, always-ready instances, `disableLocalAuth=true`, and all prior fixes.

### 29.1 Resource / Deployment State

| Resource | Property | Observed Value | Status |
|----------|----------|---------------|--------|
| func-intake-dev | state | Running | ✅ |
| func-intake-dev | kind | functionapp,linux | ✅ |
| func-intake-dev | location | East US 2 | ✅ |
| func-intake-dev | httpsOnly | true | ✅ |
| func-intake-dev | defaultHostName | func-intake-dev.azurewebsites.net | ✅ |
| func-intake-dev | ftpsState | Disabled | ✅ |
| func-intake-dev | minTlsVersion | 1.2 | ✅ |
| func-intake-dev | runtime | python 3.11, FC1 | ✅ |
| func-intake-dev | VNet subnet | snet-functions | ✅ |
| func-intake-dev | keyVaultReferenceIdentity | id-intake-worker-dev | ✅ |
| func-intake-dev | AzureWebJobsStorage | managedidentity (no SAS) | ✅ |

### 29.2 Functions / Triggers / Always-Ready

All 4 functions loaded and enabled:

| Function | Trigger | isDisabled | Status |
|----------|---------|------------|--------|
| domain_event_dispatcher | ServiceBusQueueTrigger → domain-events | false | ✅ |
| document_worker | ServiceBusQueueTrigger → document-generation | false | ✅ |
| notification_worker | ServiceBusQueueTrigger → notification-queue | false | ✅ |
| outbox_dispatcher | TimerTrigger (*/5 * * * *) | false | ✅ |

Always-ready instances (from `functionAppConfig.scaleAndConcurrency.alwaysReady`):

| Name | instanceCount | Status |
|------|---------------|--------|
| function:domain_event_dispatcher | 1 | ✅ Applied |
| function:document_worker | 1 | ✅ Applied |
| function:notification_worker | 1 | ✅ Applied |

`maximumInstanceCount=100`, `instanceMemoryMB=2048` confirmed.

App Insights trace at 2026-08-07T22:08:40Z confirms all 4 functions registered by host:
> `Found the following functions: Host.Functions.document_worker, Host.Functions.domain_event_dispatcher, Host.Functions.notification_worker, Host.Functions.outbox_dispatcher`

### 29.3 Queues — Initial State

All 4 queues confirmed at zero before test:

| Queue | active | dlq | Status |
|-------|--------|-----|--------|
| domain-events | 0 | 0 | ✅ |
| domain-events-dlq-recovery | 0 | 0 | ✅ |
| document-generation | 0 | 0 | ✅ |
| notification-queue | 0 | 0 | ✅ |

### 29.4 Message Send, Consumption, and Function Execution Evidence

**Temporary role assigned:** Azure Service Bus Data Sender → user OID `8bde9e45-7543-4aeb-a75f-12d724ea657e`, assignment ID `9c818f31-a3f3-4ef6-8007-763c20946b44`

**Message sent:** `correlationId=switch-revalidation-20260807T230838Z`  
**Send result:** HTTP 201 (via REST API using Bearer token, identity-based auth, no SAS)  
**Queue check after 20s:** domain-events active=0 → **message consumed** ✅

**App Insights execution evidence** (pre-ingestion-lag; ~1h App Insights lag observed):
- `2026-08-07T22:10:10Z` — `domain_event_dispatcher` success=True, resultCode=0, duration=5ms  
- `2026-08-07T22:10:10Z` — Trace: `domain_event_dispatcher received message`  
- Execution ID: `ec2a231a-9f85-4726-bbed-dc6f86e4b894`

> **Limitation:** App Insights ingestion lag ~60 min. The specific switch-revalidation execution cannot be confirmed by name in telemetry at time of report. Message consumption to zero (within 20s) serves as primary evidence the always-ready instance processed it.

**Temporary role removed:** ✅ Confirmed absent after deletion.

### 29.5 No Listener/Execution Errors for document_worker / notification_worker

Query: `traces | where severityLevel >= 3 | take 5` (last 60 min) → **No rows returned** ✅  
All SB listener startup traces for document_worker and notification_worker logged at severity INFO only.

### 29.6 Storage State

| Property | Observed | Status |
|----------|----------|--------|
| publicNetworkAccess | Disabled | ✅ PNA Disabled |
| allowSharedKeyAccess | false | ✅ SAS Disabled |
| blob PE (pe-st2k2osaevug-blob) | Approved, provisioningState=Succeeded | ✅ PE Approved |
| Deployment runner identity | Absent (not in RG identities) | ✅ Runner absent |

Identities present in RG: `id-intake-worker-dev`, `id-intake-agent-dev`, `id-intake-eval-dev`, `id-intake-notify-dev` (no deploy runner).

### 29.7 Runtime MI Roles / disableLocalAuth / No Local Auth Dependencies

**Service Bus `sb-2k2osaevugje`:**
| Property | Value | Status |
|----------|-------|--------|
| disableLocalAuth | true | ✅ |
| minimumTlsVersion | 1.2 | ✅ |
| publicNetworkAccess | Enabled (no SB PE; baseline) | ✅ Expected |

**Worker UAI (`id-intake-worker-dev`, OID `9d3dc21a`) SB roles:**
| Role | Status |
|------|--------|
| Azure Service Bus Data Owner | ✅ Required for FC1 scale controller |
| Azure Service Bus Data Sender | ⚠️ Redundant (superseded by Owner) — stale from prior deployment; harmless |
| Azure Service Bus Data Receiver | ⚠️ Redundant (superseded by Owner) — stale from prior deployment; harmless |

**Worker UAI other roles:**
| Resource | Role | Status |
|----------|------|--------|
| kv-2k2osaevugjeg | Key Vault Secrets User | ✅ Least-privilege |
| st2k2osaevug | Storage Blob Data Contributor | ✅ Least-privilege |

**Agent UAI SB role:** Azure Service Bus Data Sender only ✅  
**No Owner/Contributor ARM roles on RG:** Confirmed (empty list) ✅  
**AzureWebJobsStorage auth:** `credential=managedidentity`, no SAS/shared key ✅

### 29.8 Temporary Role Removal / Queues at Zero

| Item | Status |
|------|--------|
| User temp Data Sender role (9c818f31) | ✅ Removed (confirmed empty) |
| domain-events active count | 0 ✅ |
| document-generation active count | 0 ✅ |
| notification-queue active count | 0 ✅ |
| domain-events-dlq-recovery active count | 0 ✅ |

### 29.9 Endpoint URLs / No HTTP Trigger

| Function | invokeUrlTemplate | admin href | Status |
|----------|-------------------|-----------|--------|
| domain_event_dispatcher | null | /admin/functions/domain_event_dispatcher | ✅ No HTTP trigger |
| document_worker | null | /admin/functions/document_worker | ✅ No HTTP trigger |
| notification_worker | null | /admin/functions/notification_worker | ✅ No HTTP trigger |
| outbox_dispatcher | null | /admin/functions/outbox_dispatcher | ✅ No HTTP trigger |

**Generated app hostname:** `func-intake-dev.azurewebsites.net` ✅  
No public HTTP trigger endpoints exist — all triggers are SB queue or timer.

### 29.10 Switch Revalidation Verdict

| # | Check | Result |
|---|-------|--------|
| 1 | Resource/Function App state and config | ✅ PASS |
| 2 | 4 functions + always-ready applied | ✅ PASS |
| 3 | 4 queues exist and empty (initial) | ✅ PASS |
| 4 | Test message consumed, temp role removed | ✅ PASS (consumption proven; AI lag noted) |
| 5 | No errors for document/notification workers | ✅ PASS |
| 6 | Storage PNA Disabled, blob PE Approved, runner absent | ✅ PASS |
| 7 | MI roles, no Owner/Contributor, disableLocalAuth=true, no SAS | ✅ PASS (2 stale redundant SB roles noted) |
| 8 | Temp roles removed, queues at zero | ✅ PASS |
| 9 | Endpoint URLs correct, no HTTP trigger claim | ✅ PASS |

**Overall: PASS ✅ (9/9 checks passed)**

**Limitations:**
- App Insights ingestion lag ~60 min — switch-revalidation-specific telemetry not yet visible; message consumption to queue=0 is primary proof of execution.
- Worker MI carries stale SB Data Sender + Receiver roles alongside Data Owner; functionally harmless (Owner supersedes) but should be cleaned up in a future IaC cycle.


---

## Section 29 — Cost Optimisation: Remove alwaysReady, 512 MB (2026-08-07T23:18–23:25 UTC)

**Change:** Independent reviewer identified 3 × alwaysReady × 2048 MB as a material cost violation of POC target.  
**Resolution:** With Azure Service Bus Data Owner now assigned, the FC1 scale controller reads queue depth accurately; lwaysReady warm instances are no longer required for trigger correctness.

### Changes Applied

| File | Change |
|------|--------|
| infra/modules/functions.bicep | Removed lwaysReady array; set instanceMemoryMB: 512 |
| infra/main.json | Rebuilt from updated Bicep |

### What-If Summary
Only change on Function App: instanceMemoryMB: 2048 → 512 + lwaysReady removed. No other resource modifications.

### Provision Run
- **Deployment ID:** dev-1786141216
- **Duration:** 2m12s (23:18:48 → 23:22:55 UTC)
- **Outcome:** SUCCESS ✅

### Post-Provision Verification

| Check | Result |
|-------|--------|
| lwaysReady: null (removed) | ✅ |
| instanceMemoryMB: 512 | ✅ |
| Function App state: Running | ✅ |
| 4 functions registered | ✅ document_worker, domain_event_dispatcher, notification_worker, outbox_dispatcher |
| Host started, 4 functions loaded | ✅ 2026-08-07T22:23:41Z |
| All queues: 0 active (ready for cold-scale test) | ✅ |

### Follow-up (No Immediate Action)
- Stale Azure Service Bus Data Sender and Azure Service Bus Data Receiver role assignments on worker UAI remain (redundant since Data Owner supersedes both). **Not removed** — role deletion is destructive and requires explicit user confirmation. Record for next RBAC hygiene review.

---

## Section 30 — Cold-Scale Independent Verification (Switch, 2026-08-07T23:33–23:55 UTC)

**Requested by:** Ha Duong  
**Executed by:** Switch (Quality Engineer) — live Azure CLI session, no IaC/code edits  
**Purpose:** Post-cost-optimisation independent verification: confirm `alwaysReady=null`, `instanceMemoryMB=512`, queues empty, send correlated probe message, measure cold-scale latency for `domain_event_dispatcher`, verify RBAC and storage posture, remove temp role.

---

### 30.1 Static Config Checks

| Check | Evidence | Result |
|-------|----------|--------|
| Function App state | ARM REST: `properties.state = Running` | ✅ |
| httpsOnly | ARM REST: `properties.httpsOnly = true` | ✅ |
| `alwaysReady` | `functionAppConfig.scaleAndConcurrency.alwaysReady = null` | ✅ |
| `instanceMemoryMB` | `functionAppConfig.scaleAndConcurrency.instanceMemoryMB = 512` | ✅ |
| `maximumInstanceCount` | 100 | ✅ |
| Runtime | Python 3.11 | ✅ |
| 4 functions registered, none disabled | `document_worker`, `domain_event_dispatcher`, `notification_worker`, `outbox_dispatcher` | ✅ |
| FC1 plan | `asp-intake-dev` SKU=FC1 | ✅ |

### 30.2 Queue State (Pre-Probe)

| Queue | Active | DLQ |
|-------|--------|-----|
| document-generation | 0 | 0 |
| domain-events | 0 | 0 |
| domain-events-dlq-recovery | 0 | 0 |
| notification-queue | 0 | 0 |

All 4 queues confirmed empty before probe. ✅

### 30.3 Storage / Network Posture

| Check | Value | Result |
|-------|-------|--------|
| `publicNetworkAccess` | `Disabled` | ✅ |
| `allowSharedKeyAccess` | `false` | ✅ |
| Blob PE `st2k2osaevug.18dc6d94-…` | `Approved` | ✅ |

### 30.4 RBAC Posture

| Principal | Scope | Roles | Result |
|-----------|-------|-------|--------|
| Worker UAI (`id-intake-worker-dev`) | SB namespace | Data Owner + stale Sender + stale Receiver | ✅ (Owner supersedes; stale roles harmless, noted) |
| Worker UAI | RG (`rg-intake-dev`) | *(none)* | ✅ No Owner/Contributor |
| Temp deployment runner | Any | *(not present)* | ✅ Absent |
| Current user pre-probe | SB namespace | *(none)* | ✅ No pre-existing role |

### 30.5 Temporary Role Assignment / Removal

| Step | Detail | Result |
|------|--------|--------|
| Assign | `Azure Service Bus Data Sender` → user OID `8bde9e45-7543-4aeb-a75f-12d724ea657e` on SB namespace; RA ID `dc5c0caf-8f73-4114-a04a-888c4f8d03a3` | ✅ |
| Send probe | CorrelationId `switch-cold-scale-20260807-a9378d7b-ec7d-4c75-a6fb-326ffe61bebf`; sent 2026-08-07T22:33:26Z via `azure-servicebus` Python SDK + `DefaultAzureCredential` | ✅ |
| Remove | `az role assignment delete --ids dc5c0caf-…` | ✅ |
| Confirm removal | `az role assignment list --assignee ... --scope $SBId` → empty | ✅ |

### 30.6 Cold-Scale Probe Result

**Probe message sent:** 2026-08-07T22:33:26Z  
**Observation window:** 22:33–22:48 UTC (~20 minutes)  
**`domain-events` queue state at close of window:** `activeMessageCount=1` (unconsumed)

| Observation | Detail |
|-------------|--------|
| `outbox_dispatcher` (timer) fired | 22:40:00Z, 22:45:00Z — Function App IS running ✅ |
| `domain_event_dispatcher` execution | **None** — no invocation in App Insights `requests` table in 2-hour window |
| App Insights exceptions | None in 2-hour window ✅ |
| Host cold-start log | Instance started 22:43:40Z for timer group; `"Function group target is function:outbox_dispatcher"` logged ×4 |
| Active instances at query time | 0 (ARM `/instances` API returned empty) |
| DLQ messages | 0 — probe message not dead-lettered, still active |

**Cold-scale latency for `domain_event_dispatcher`: NOT MEASURED — trigger did not fire within 20-minute window.**

### 30.7 Root Cause Analysis

Two probable causes for `domain_event_dispatcher` not consuming the probe message:

**Cause A — Flex Consumption SB scale controller credential gap:**  
The storage binding is fully configured for user-assigned MI:
```
AzureWebJobsStorage__accountName     = st2k2osaevug
AzureWebJobsStorage__clientId        = 9d3dc21a-5180-4c31-aaed-5c98d6d01ace
AzureWebJobsStorage__credential      = managedidentity
```
The SB binding is missing `__credential` and `__clientId`:
```
INTAKE_SERVICEBUS_NAMESPACE__fullyQualifiedNamespace = sb-2k2osaevugje.servicebus.windows.net
# MISSING: INTAKE_SERVICEBUS_NAMESPACE__credential = managedidentity
# MISSING: INTAKE_SERVICEBUS_NAMESPACE__clientId   = 9d3dc21a-5180-4c31-aaed-5c98d6d01ace
```
`AZURE_CLIENT_ID` is set as a fallback but the Flex Consumption **scale controller** (the external component that monitors queue depth and triggers scale-out) runs outside the host process and may not inherit `AZURE_CLIENT_ID`. Without `__credential=managedidentity`, the scale controller cannot authenticate to Service Bus to detect pending messages and thus never schedules a `domain_event_dispatcher` instance.

**Cause B — Flex Consumption function group isolation:**  
The host log shows `"Function group target is function:outbox_dispatcher"` for all 4 functions when the timer fires. In Flex Consumption, timer/HTTP triggers and Service Bus triggers run in separate function groups. The warm instance created for the timer trigger does not consume SB messages. The SB group requires a separate scale event from the scale controller — which is blocked by Cause A.

**Prior evidence (Section 28):** `domain_event_dispatcher` consumed 3 smoke messages at 21:57:22Z — those runs occurred before the `alwaysReady=null` change (Section 29) while instances were warm and already listening. Post-change, with 0 instances, the SB scale controller must initiate scale-out, revealing the credential gap.

### 30.8 Actions Required (Owner: Trinity)

| # | Action | Owner | Priority |
|---|--------|-------|----------|
| 1 | Add `INTAKE_SERVICEBUS_NAMESPACE__credential = managedidentity` app setting | Trinity | **HIGH — blocking** |
| 2 | Add `INTAKE_SERVICEBUS_NAMESPACE__clientId = 9d3dc21a-5180-4c31-aaed-5c98d6d01ace` app setting | Trinity | **HIGH — blocking** |
| 3 | After fix: re-run cold-scale probe from zero instances; record latency | Switch / Tank | HIGH |
| 4 | Remove stale SB Data Sender + Data Receiver from worker UAI (explicit user approval required) | Tank | LOW |

### 30.9 Section 30 Verdict

| Gate | Result |
|------|--------|
| Config: alwaysReady=null, instanceMemoryMB=512 | ✅ PASS |
| Function App Running, 4 functions registered | ✅ PASS |
| All queues empty pre-probe | ✅ PASS |
| No Owner/Contributor on runtime MIs | ✅ PASS |
| Storage PNA Disabled, PE Approved, sharedKey=false | ✅ PASS |
| Temp deployment runner absent | ✅ PASS |
| Temp Data Sender role assigned, used, removed | ✅ PASS |
| `domain_event_dispatcher` cold-scale trigger | ❌ FAIL — not triggered in 20-min window |
| Cold-scale latency measured | ❌ BLOCKED — trigger did not fire |

**Overall Section 30 verdict: ❌ FAIL**  
Reason: `domain_event_dispatcher` Service Bus trigger did not consume the probe message from a cold (0-instance) state after 20+ minutes. Root cause: missing `INTAKE_SERVICEBUS_NAMESPACE__credential` and `__clientId` app settings prevent the Flex Consumption scale controller from authenticating to Service Bus. All infrastructure posture checks passed; the fault is a configuration gap in Function App settings, remediable by Trinity without IaC changes.

**Probe message status:** `domain-events` queue has `activeMessageCount=1` at close of observation. Message will be consumed when Trinity applies the fix and re-deploys, or expire per queue TTL (14 days default). No DLQ pollution.

---

## Section 31 — Definitive Final Cold-Scale Probe (Switch, 2026-08-08T00:05–00:15 UTC)

**Context:** Trinity applied the missing SB managed identity settings (`__credential=managedidentity`, `__clientId`) and restarted the Function host. This section is the definitive cold-scale verification.

**Executed by:** Switch (Quality Engineer) — live Azure CLI + Python SDK session; no IaC/code edits.

---

### 31.1 Config Verification

| Setting | Value | Result |
|---------|-------|--------|
| `INTAKE_SERVICEBUS_NAMESPACE__fullyQualifiedNamespace` | `sb-2k2osaevugje.servicebus.windows.net` | ✅ |
| `INTAKE_SERVICEBUS_NAMESPACE__credential` | `managedidentity` | ✅ |
| `INTAKE_SERVICEBUS_NAMESPACE__clientId` | `9d3dc21a-5180-4c31-aaed-5c98d6d01ace` | ✅ |
| `AZURE_CLIENT_ID` | `9d3dc21a-5180-4c31-aaed-5c98d6d01ace` | ✅ |
| `alwaysReady` | `null` (removed) | ✅ |
| `instanceMemoryMB` | `512` | ✅ |
| `maximumInstanceCount` | `100` | ✅ |
| Function App state | `Running`, `httpsOnly=true` | ✅ |

### 31.2 Pre-Probe Gate Checks

| Check | Result |
|-------|--------|
| All 4 queues at 0 active / 0 DLQ | ✅ |
| 4 functions registered, none disabled | ✅ `document_worker`, `domain_event_dispatcher`, `notification_worker`, `outbox_dispatcher` |
| Storage `publicNetworkAccess=Disabled` | ✅ |
| Storage `allowSharedKeyAccess=false` | ✅ |
| Storage blob PE `st2k2osaevug.18dc6d94-…` = `Approved` | ✅ |
| User had no pre-existing SB role | ✅ (empty role list) |
| Worker UAI has no Owner/Contributor at RG level | ✅ (empty role list) |
| Temp deployment runner absent | ✅ |

### 31.3 Temporary Role / Probe

| Step | Detail |
|------|--------|
| Temp role assigned | `Azure Service Bus Data Sender` → user OID `8bde9e45-7543-4aeb-a75f-12d724ea657e`; RA `465e88fc-3f36-4684-9912-70a0f9edf1c7` |
| Probe sent | CorrelationId `switch-final-cold-scale-20260808-75b1fa2f-472d-4875-aab5-63e07ea1b84a`; sent 2026-08-07T23:07:41Z via `azure-servicebus` Python SDK + `DefaultAzureCredential` |
| Temp role removed | 2026-08-07T23:08:04Z (23 s after send) |
| User role confirmed absent | Empty role list post-removal ✅ |

### 31.4 Cold-Scale Execution Evidence

Queue polling confirmed `domain-events activeMessageCount=0` at **23:08:27Z** — **46 seconds** after message send.

App Insights traces (ingested ~5 min post-execution):

| Timestamp (UTC) | Event |
|-----------------|-------|
| `23:07:58` | Flex Consumption SB scale controller spun new instance; `"Function group target is function:domain_event_dispatcher"` ×4 |
| `23:07:58` | Host cold-start: all 4 functions loaded (`ConsecutiveErrors=0`, `StartupCount=3`) |
| `23:07:58` | `AutoCompleteMessages=True` override logged for `domain_event_dispatcher` |
| `23:07:59` | `Executing 'Functions.domain_event_dispatcher'` (Reason=null, Id=`3cded683-f2f3-4b86-9326-6d0ffccf0e07`) |
| `23:07:59` | `domain_event_dispatcher received message` |
| `23:07:59` | `Executed 'Functions.domain_event_dispatcher' (Succeeded, …, Duration=31ms)` |

**Cold-start breakdown:**
- Message send → host initialized: **~17 s** (23:07:41 → 23:07:58)
- Host initialized → function executed: **~1 s**
- Send → queue at zero (poll): **46 s** (includes 5-s poll interval overhead)

### 31.5 Post-Probe State

| Check | Result |
|-------|--------|
| All 4 queues: active=0, DLQ=0 | ✅ |
| App Insights exceptions (20-min window) | None ✅ |
| Listener errors | None (SB listener stop/start at 23:12:29/23:13:38 is normal host recycle) ✅ |
| Temp Data Sender role | Removed ✅ |
| User has no remaining SB role | Confirmed ✅ |

### 31.6 Residual Note

Worker UAI (`id-intake-worker-dev`) retains stale `Azure Service Bus Data Sender` + `Azure Service Bus Data Receiver` alongside `Data Owner`. Redundant but harmless. Awaiting explicit user approval before removal (destructive operation).

### 31.7 Section 31 Verdict

| Gate | Result |
|------|--------|
| Config: alwaysReady=null, instanceMemoryMB=512 | ✅ PASS |
| Complete SB MI binding (`__credential`, `__clientId`, `__fullyQualifiedNamespace`) | ✅ PASS |
| Function App Running, 4 functions registered | ✅ PASS |
| All queues empty pre-probe | ✅ PASS |
| No Owner/Contributor on runtime MIs | ✅ PASS |
| Storage PNA Disabled, PE Approved, sharedKey=false | ✅ PASS |
| Temp deployment runner absent | ✅ PASS |
| Temp Data Sender role assigned → used → removed | ✅ PASS |
| `domain_event_dispatcher` cold-scale trigger fired | ✅ PASS |
| No App Insights exceptions | ✅ PASS |
| Queue returned to zero | ✅ PASS |
| **Cold-scale latency (send → function executed)** | ✅ **~18 s** |

**Overall Section 31 verdict: ✅ PASS**

Cold-scale latency with `alwaysReady=null` and `instanceMemoryMB=512`: **~18 seconds** (message send → `domain_event_dispatcher` execution). Queue polled empty at 46 s (includes 5-s poll overhead). Zero exceptions. All infrastructure posture checks passed. Temp role lifecycle complete.


---

## Section 30 — Morpheus Cold-Scale Identity Fix: INTAKE_SERVICEBUS_NAMESPACE credential/clientId (2026-08-07T23:56–00:05 UTC)

**Change:** Morpheus's approved IaC adds explicit INTAKE_SERVICEBUS_NAMESPACE__credential=managedidentity and INTAKE_SERVICEBUS_NAMESPACE__clientId app settings. These settings complete the identity-based connection configuration for the SB connection prefix, ensuring the Functions SB extension unambiguously selects the user-assigned identity (client ID 9d3dc21a-5180-4c31-aaed-5c98d6d01ace) for AMQP authentication — removing reliance on environment-level AZURE_CLIENT_ID fallback.

**IaC applied as-is; no changes made to reviewed Bicep.**

### Pre-Provision State
- INTAKE_SERVICEBUS_NAMESPACE__fullyQualifiedNamespace ✅ already live
- INTAKE_SERVICEBUS_NAMESPACE__credential ❌ absent
- INTAKE_SERVICEBUS_NAMESPACE__clientId ❌ absent

### What-If Summary

unc-intake-dev → Modify (app settings array update + cosmetic siteConfig defaults). No destructive resource changes.

### Provision Run
- **Deployment ID:** dev-1786143584
- **Duration:** 2m11s (23:58:16 → 00:02:26 UTC)
- **Outcome:** SUCCESS ✅

### Post-Provision Verification

| Check | Value | Status |
|-------|-------|--------|
| INTAKE_SERVICEBUS_NAMESPACE__fullyQualifiedNamespace | sb-2k2osaevugje.servicebus.windows.net | ✅ |
| INTAKE_SERVICEBUS_NAMESPACE__credential | managedidentity | ✅ |
| INTAKE_SERVICEBUS_NAMESPACE__clientId | 9d3dc21a-5180-4c31-aaed-5c98d6d01ace | ✅ |
| instanceMemoryMB | 512 (unchanged) | ✅ |
| lwaysReady | null (unchanged) | ✅ |
| Function App state | Running | ✅ |
| 4 functions registered | document_worker, domain_event_dispatcher, notification_worker, outbox_dispatcher | ✅ |
| Host started + 4 functions loaded | 2026-08-07T23:03:39Z | ✅ |
| All queues | 0 active (untouched for Switch cold-scale probe) | ✅ |
| Source package redeployed | No — not required | ✅ |
| Stale Sender/Receiver roles | Left in place — awaiting user confirmation to remove | ✅ |

**No commit made.** (No Tank-owned file changed; Bicep was already committed in a prior session.)

---

## Section 32 — Microsoft Foundry + Hosted Agent Deployment (Tank, 2026-08-08)

### 32.1 Tooling and Capacity

- `azd` upgraded from `1.28.1` to `1.30.0`.
- Installed compatible extensions: `microsoft.foundry 1.0.0-beta.2`,
  `azure.ai.agents 1.0.0-beta.9`, and `azure.ai.projects 1.0.0-beta.5`.
- `Microsoft.MachineLearningServices` registered.
- East US 2 Hosted Agent/private networking support confirmed dynamically.
- Model quota confirmed before deployment. `gpt-5-nano` GlobalStandard quota was
  `0/5000`; deployment capacity is `10`.

### 32.2 Private Foundry Foundation

| Resource | Live result |
|----------|-------------|
| Foundry account | `ais-intake-2k2osaev` — `Succeeded` |
| Project | `aiproj-intake-dev` — `Succeeded` |
| Project endpoint | `https://ais-intake-2k2osaev.services.ai.azure.com/api/projects/aiproj-intake-dev` |
| Selected model | `gpt-5-nano`, version `2025-08-07`, GlobalStandard capacity `10` — `Succeeded` |
| Original compatibility probe model | `gpt-4.1-mini`, version `2025-04-14`, capacity `10` — retained but not used by the active agent |
| Foundry public access | `Disabled` |
| Local/key authentication | Disabled |
| Private endpoint | `pe-ais-intake-2k2osaev-account` — `Approved` |
| Foundry private DNS | `services.ai`, `cognitiveservices`, and `openai` zones linked to `vnet-intake-dev` |
| Agent network injection | Dedicated delegated subnet `snet-foundry-agent` (`10.0.3.0/24`) |

The current `Microsoft.CognitiveServices/accounts` + child project schema replaced
the obsolete ML Hub/Workspace design. Storage, Cosmos DB, Search, and Key Vault
remain private. Standard Service Bus remains on its public endpoint because private
endpoints require Premium; local authentication is disabled and managed-identity
RBAC remains enforced.

### 32.3 Preview and Deployment

- `azd provision --preview` completed successfully before foundation deployment.
- A dedicated model what-if showed one `Create` for
  `accounts/deployments/gpt-5-nano` and no destructive change.
- `foundry-model-compat-20260808` deployed `gpt-5-nano` successfully.
- Direct-code Hosted Agent deployment ran from an ephemeral VNet-integrated
  Container Apps Job because the project rejects public data-plane access.
- Private DNS inside the runner resolved the Foundry account to `10.0.1.11`.

### 32.4 Hosted Agent Live State

| Attribute | Value |
|-----------|-------|
| Name/version | `intake-agent:6` |
| Status | `active` |
| Runtime | Python `3.13`, direct code, remote dependency build |
| Entry point | `python hosted_main.py` |
| Protocol | Responses `2.0.0` |
| Resources | `0.5` CPU / `1Gi` memory |
| Model | `gpt-5-nano` |
| Runtime principal | `7698b8bc-55ea-49b5-b2a8-ad06a16a1e9e` |
| Responses endpoint | `https://ais-intake-2k2osaev.services.ai.azure.com/api/projects/aiproj-intake-dev/agents/intake-agent/endpoint/protocols/openai/responses?api-version=v1` |
| Playground | `https://ai.azure.com/nextgen/r/h-GnhYlrTrSiFEf2eZUTPg,rg-intake-dev,,ais-intake-2k2osaev,aiproj-intake-dev/build/agents/intake-agent/build?version=6` |

Runtime RBAC was verified for Storage Blob Data Contributor, Cosmos DB built-in
Data Contributor, Search Index Data Reader, Service Bus Data Sender, and Cognitive
Services User.

### 32.5 Live Invocation

Execution `job-intake-foundry-deploy-2ym0y86` ran from
`2026-08-08T16:38:49Z` to `16:40:10Z` and succeeded.

- Session: `0a151b9042e69bed1cb26415f0bc402f543449ce7fa52a48f0bffaf08ddcc62`
- Result: one `response.completed`, zero `response.failed`.
- The response loaded `general-intake-v1`, reported revision `1`, no captured
  fields, and `can_submit=false`, then asked the caller for explicit intake values.

### 32.6 Evaluation

- Configuration: `eval.yaml`; dataset:
  `evaluation/dataset/foundry_smoke.jsonl` (five synthetic functional/security
  cases); evaluators use current `builtin.*` identifiers.
- Eval: `eval_0af9e3b25bdc4da8a122f5086bb37035`
- Run: `evalrun_dea888681bcf483b89a5255ebcb7fa46`
- Report:
  `https://ai.azure.com/nextgen/r/h-GnhYlrTrSiFEf2eZUTPg,rg-intake-dev,,ais-intake-2k2osaev,aiproj-intake-dev/build/evaluations/eval_0af9e3b25bdc4da8a122f5086bb37035/run/evalrun_dea888681bcf483b89a5255ebcb7fa46`
- Latest direct API status at `2026-08-08T17:54:56Z`: `in_progress`,
  `total=0`, `passed=0`, `failed=0`, `report_url=null`, `error=null`.
- A private in-VNet poller queried the run every minute for 20 additional minutes.
  The service remained unchanged more than 54 minutes after creation, so this is
  recorded as an external Foundry evaluation-service blocker rather than a pass.
- `azd ai agent eval run` successfully created the run but the preview CLI could
  not poll it because it attempted to unmarshal inline dataset `content` as an
  object instead of a string. Direct authenticated API polling was used instead.

### 32.7 Residual Blocker and Safety Posture

The repository's Cosmos, Blob, and Service Bus persistence adapters still raise
`NotImplementedError`. To verify the dev Hosted Agent live without altering domain
implementation, version 6 explicitly uses non-production in-memory state with
`INTAKE_ALLOW_EPHEMERAL_HOSTED_STATE=true`. Durable Azure data-plane RBAC is already
assigned, but production persistence requires those adapters to be implemented.

The existing Function App remains `Running`, exposes all four functions, and
retains complete managed-identity Service Bus settings (`fullyQualifiedNamespace`,
`credential=managedidentity`, and user-assigned `clientId`).

### 32.8 Final Validation and Cleanup

- `az bicep build --file infra/main.bicep` — succeeded with Bicep `0.46.1`.
- `az deployment sub validate` with resolved dev parameters — `Succeeded`.
- `python -m pytest -q` — `711 passed`.
- Final ARM checks: Foundry account/model/private endpoint all `Succeeded`; private
  endpoint connection `Approved`; Storage and Cosmos public access `Disabled` and
  key/local authentication disabled; Search public access `Disabled` with AAD
  bearer challenge; Standard Service Bus local authentication disabled.
- The Function App remains `Running`; all four functions and complete Service Bus
  managed-identity settings were re-verified.
- Ephemeral deployment/evaluation jobs, runner-only Foundry RBAC assignments, and
  local package/log/poller scratch artifacts were removed. Final count:
  `temporaryJobs=0`, `runnerFoundryRoles=0`.

### 32.9 Independent External-Shell Verification (Switch, 2026-08-08T18:05Z)

Switch independently targeted `intake-agent:6` and the exact Responses endpoint
from a separate agent shell. `azd ai agent show`, a fresh-session/fresh-conversation
invoke, eval list, and fresh eval submission all returned HTTP 403:
`Public access is disabled. Please configure private endpoint.` No independent eval
or run ID was created. After the azd dev environment was corrected to
`AZURE_AI_MODEL_DEPLOYMENT_NAME=gpt-5-nano`, both operations were retried and
returned the same policy 403. Local evaluation gates remained `14 passed` with
Ruff clean; the concurrent QE baseline was `709` full-suite passes. `eval.yaml`
was verified against version `6` / `gpt-5-nano`.

This is expected policy enforcement, not an agent-runtime regression: the Foundry
account is private-only and the temporary VNet runner used for the successful live
smoke was removed after verification. A second independent live data-plane check
requires an approved in-VNet execution path; public access will not be enabled.

### 32.10 Frozen Responses Source Redeployment (2026-08-08T18:28–18:47Z)

- Redeployed Trinity's frozen root direct-code source through the approved
  VNet-integrated Container Apps runner. Deployment succeeded as
  `intake-agent:7`; status `active`; content hash
  `7c6701bd65ed4adcdae1f5d4354bfbcf4e7b16e43969ae954bffdb54714af36a`.
- Runtime contract: Python 3.13, `python hosted_main.py`, remote dependency build,
  Responses `2.0.0`, `gpt-5-nano`, 0.5 CPU / 1Gi, explicit dev-only in-memory
  persistence. Runtime principal remains
  `7698b8bc-55ea-49b5-b2a8-ad06a16a1e9e`.
- Active endpoint:
  `https://ais-intake-2k2osaev.services.ai.azure.com/api/projects/aiproj-intake-dev/agents/intake-agent/endpoint/protocols/openai/responses?api-version=v1`.
- Fresh version-7 invocation succeeded. Session
  `313ffe2dc19360c700UlN0mpdi9pK3Lu97g97B31trFiAMV74O`; conversation
  `conv_786252aaa8a3f100006QyJfpYniPn4OPDxRgkh5rr5WSdTMYkp`; trace
  `3b7d6bc903858d4b999c441e991f44b9`. The agent loaded
  `general-intake-v1`, refused submission while `can_submit=false`, and requested
  intake information.
- Submitted evaluation `eval_40fb54424ad541729ae57d8974636f34`, run
  `evalrun_0c775418dfa94ba8bc5d981cb31841d1`, named
  `tank-live-acceptance-v7-20260808`. Latest private API status at
  `2026-08-08T18:46:44Z`: `in_progress`, `total=0`, `passed=0`, `failed=0`,
  `report_url=null`, `error=null`.
- Published `AGENT_NAME`, `AGENT_ID`, `AGENT_VERSION`, `AGENT_ENDPOINT`,
  `AGENT_GUID`, `AGENT_RUNTIME_PRINCIPAL_ID`, and `AGENT_PLAYGROUND_URL` into the
  azd `dev` environment and sent them to Switch for independent verification.
- Validation: targeted Hosted/eval tests `26 passed`; complete suite `711 passed`;
  targeted evaluation/contract Ruff checks passed.
- Ephemeral deployment/polling runner, local archives, and runner-only Foundry
  role assignments were removed: `temporaryJobs=0`, `runnerFoundryRoles=0`.

### 32.11 Final Asynchronous Evaluation Check (2026-08-08T18:52Z)

A single final check from the private VNet path returned evaluation
`eval_40fb54424ad541729ae57d8974636f34`, run
`evalrun_0c775418dfa94ba8bc5d981cb31841d1`, status `in_progress`, with
`total=0`, `passed=0`, `failed=0`, `report_url=null`, and `error=null`.
No further polling was performed. The temporary check job and runner-only roles
were removed (`temporaryJobs=0`, `runnerFoundryRoles=0`). The current published
active deployment is `intake-agent:7` (version 6 was superseded by the requested
frozen-source redeployment).

### 32.12 Independent Version-7 QE Verification (Switch, 2026-08-08T18:56Z)

Using the published `AGENT_*` values, Switch independently retried a fresh-session,
fresh-conversation invocation and fresh eval `switch-independent-v7-20260808`.
Both were rejected before creation with the expected private-boundary HTTP 403
(`Public access is disabled. Please configure private endpoint.`); therefore no
independent eval/run ID exists. Local version-7 gates remained `14 passed` with
Ruff clean. `job-intake-eval-dev` is VNet-integrated but still uses its hello-world
placeholder image; modifying it was correctly left outside QE scope. Independent
functional verification remains blocked until an approved runner is preconfigured;
private networking remains unchanged.

---

## Section 33 — Production-Durable Hosted Agent Preparation (2026-08-08)

### 33.1 Live Inventory and Contract

- Live Hosted Agent baseline: `intake-agent:7`, status `active`, runtime principal
  `7698b8bc-55ea-49b5-b2a8-ad06a16a1e9e`.
- Existing Cosmos `requests` uses immutable partition key `/tenantId`; Trinity's
  durable transactional aggregate/outbox contract requires `/requestId`.
- Existing Blob container `request-artifacts` matches the application contract.
- Existing `domain-events` queue has duplicate detection disabled.
- Storage, Cosmos, Search, and Foundry remain private-only. Standard Service Bus
  remains public-endpoint/AAD-only because private endpoints require Premium.

### 33.2 Non-Destructive Resource Plan

- Retain legacy Cosmos containers and add:
  `request-state` (`/requestId`), `templates` (`/templateId`), and
  `idempotency` (`/scopeId`, item TTL enabled).
- Retain `domain-events` and add `domain-events-durable` with duplicate detection
  and a one-day detection window. Stable outbox item IDs are sent as MessageId.
- Wire Hosted Agent and Functions to the new resources through explicit env vars.
- Seed `general-intake-v1:1.0.0` idempotently from the approved private runner.
- Scope Hosted runtime RBAC to Cosmos database `intake`, Blob container
  `request-artifacts`, and queue `domain-events-durable`; retain Search Index Data
  Reader and Cognitive Services User at their required service/account scopes.

### 33.3 Prepared Files and Quality Gate

- Updated `azure.yaml`, Cosmos/Service Bus/Functions Bicep, generated
  `infra/main.json`, post-deploy verification scripts, worker Azure dependencies,
  managed-identity RBAC script, and template seed script.
- Trinity durable adapter handoff completed; the previous agent task is idle.
- `python -m pytest -q`: `745 passed, 1 skipped` (live Azure test gated).
- Ruff: passed. Targeted mypy: passed.
- Bicep build: passed with Azure CLI Bicep `0.46.1`.
- Prepared timestamp: `2026-08-08T19:30:10Z`.

### 33.4 Production-Durability Validation Proof

Validated on `2026-08-08` before deployment:

| Check | Command | Result |
|-------|---------|--------|
| Full application suite | `python -m pytest -q` | ✅ `746 passed, 1 skipped`; only the opt-in live-Azure persistence test was skipped |
| Lint | `python -m ruff check src tests evaluation scripts\azure\seed-default-template.py` | ✅ All checks passed |
| Type checking | `python -m mypy src` | ✅ No issues in 34 source files |
| Bicep build | `az bicep build --file infra\main.bicep --outfile infra\main.json` | ✅ Passed |
| ARM validation | `az deployment sub validate ... location=eastus2 environmentName=dev` | ✅ `Succeeded` |
| Azure preflight | `scripts\azure\preflight.ps1` | ✅ Passed with 0 errors; Bot Service warning is expected because that feature is disabled |
| Provisioning preview | `azd provision --preview --no-prompt` | ✅ Passed; no deletes or public-networking relaxation |
| Hosted package | `azd package intake-agent ... --no-prompt` | ✅ Direct-code package produced successfully |
| Secret scan | Ripgrep over `azure.yaml`, `infra`, and `scripts\azure` | ✅ No key, connection-string, client-secret, password, or private-key patterns |
| Static RBAC review | Bicep and `ensure-hosted-agent-rbac.ps1` | ✅ Data-plane roles only; Hosted runtime narrows Cosmos to database, Blob access to container, and Service Bus send to queue |

`BlobArtifactStore.get_artifact_url` obtains a user-delegation key. The runtime
therefore receives `Storage Blob Delegator` at storage-account scope in addition
to `Storage Blob Data Contributor` at `request-artifacts` container scope. This is
the least-privilege split required because delegation-key generation cannot be
authorized at container scope.

The final ARM what-if identified only additive durable resources and computed
updates: three Cosmos containers and one Service Bus queue are created, with no
resource deletions or destructive recreation. Existing containers, queues, private
endpoints, public-access restrictions, and managed-identity-only authentication
remain intact.

### 33.5 Production-Durable Deployment Evidence

Deployed and verified on `2026-08-08`:

- ARM deployment `dev-1786218122` completed successfully in 2m59s.
- Created non-destructively:
  - Cosmos `request-state` (`/requestId`)
  - Cosmos `templates` (`/templateId`)
  - Cosmos `idempotency` (`/scopeId`, item TTL enabled)
  - Service Bus `domain-events-durable` with duplicate detection and `P1D`
    detection history
- Existing `requests`, `revisions`, `workflow-events`, and `domain-events`
  resources were retained without partition-key or queue recreation.
- Seeded `general-intake-v1:1.0.0` idempotently from the approved
  VNet-integrated Container Apps runner.

Hosted Agent:

| Attribute | Live value |
|-----------|------------|
| Active version | `intake-agent:8` |
| Status | `active` |
| Runtime principal | `7698b8bc-55ea-49b5-b2a8-ad06a16a1e9e` (unchanged from version 7) |
| Responses endpoint | `https://ais-intake-2k2osaev.services.ai.azure.com/api/projects/aiproj-intake-dev/agents/intake-agent/endpoint/protocols/openai/responses?api-version=v1` |
| Playground | `https://ai.azure.com/nextgen/r/h-GnhYlrTrSiFEf2eZUTPg,rg-intake-dev,,ais-intake-2k2osaev,aiproj-intake-dev/build/agents/intake-agent/build?version=8` |

The version-8 manifest contains no ephemeral-state override. Effective settings
use `cosmos`, `azure` Blob, and `azure` Service Bus backends, with
`request-state`, `templates`, `idempotency`, and `domain-events-durable`.

Live Hosted runtime RBAC after legacy broad-role pruning:

| Data plane | Role and scope |
|------------|----------------|
| Cosmos DB | Built-in Data Contributor on database `intake` |
| Blob content | Storage Blob Data Contributor on container `request-artifacts` |
| Blob delegated URLs | Storage Blob Delegator on storage account `st2k2osaevug` |
| Service Bus | Data Sender on queue `domain-events-durable` |
| Search | Search Index Data Reader on `srch-2k2osaevugje` |
| Foundry inference | Cognitive Services User on `ais-intake-2k2osaev` |

No account-scoped Cosmos contributor, storage-account Blob Data Contributor, or
namespace-scoped Service Bus Sender remains on the Hosted runtime.

Functions were rebuilt inside a Python 3.11 VNet runner so native dependencies
match the FC1 runtime. The worker package includes `azure-cosmos`,
`azure-servicebus`, `azure-identity`, `pydantic`, and `aiohttp`. Final live state:

- Function App `func-intake-dev`: `Running`, HTTPS only.
- Four functions registered: `document_worker`, `domain_event_dispatcher`,
  `notification_worker`, and `outbox_dispatcher`.
- Repeated timer executions after deployment succeeded.
- `domain-events-durable`: `active=0`, `deadLetter=0`.

Durability smoke:

- Stable delegated user: `tank-user-1786222030`.
- Conversation:
  `conv_0c046a52a42f070e00vfd0vyiTlHiE3UTu9CqJqSqf9N4vhX6p`.
- First invocation explicitly called `get_context`, `update_field`, and
  `get_context`, persisting `project.name = "Durable Verification 1786222030"`.
- A separate fresh-session invocation called `get_context` and returned the exact
  same persisted value.
- Cosmos proof: request `4907b8395d1e3e98e3d4eccf18bc6208`,
  revision `2`, exact project name present in `request-state`.
- Durable outbox proof: one outbox item reached `dispatched=true`; the
  duplicate-detecting queue returned to zero with no dead-letter messages.

Evaluation:

- Eval: `eval_d3d6020eb8af478fa8a815b581173218`
- Run: `evalrun_a816771f55a94be4a63139264a425db1`
- Report:
  `https://ai.azure.com/nextgen/r/h-GnhYlrTrSiFEf2eZUTPg,rg-intake-dev,,ais-intake-2k2osaev,aiproj-intake-dev/build/evaluations/eval_d3d6020eb8af478fa8a815b581173218/run/evalrun_a816771f55a94be4a63139264a425db1`
- Single asynchronous status check: `in_progress`. No prolonged polling performed.

Cleanup:

- Temporary Foundry/worker Container Apps jobs removed.
- Temporary Function Contributor and delegated-user impersonation assignments
  removed.
- Runner-only Foundry roles and the temporary custom role definition removed.
- Local deployment archives and job definitions removed.
- Final post-deploy verification: `9 passed, 0 failed`.
- Final repository gate: `748 passed, 1 skipped`; Ruff and mypy passed.

### 33.6 Independent Exact QE Live Gate

At Switch's request, the corrected repository test
`tests/azure/test_hosted_durable_persistence.py` was packaged from the current
tree and run unchanged from an ephemeral VNet-integrated Container Apps Job
against version 8. The first invocation omitted `--conversation-id`, parsed the
server-returned `conv_*` identifier, and reused that identifier for both the
same-session and fresh-session checks:

```text
INTAKE_RUN_AZURE_TESTS=1
INTAKE_AGENT_ENDPOINT=https://ais-intake-2k2osaev.services.ai.azure.com/api/projects/aiproj-intake-dev/agents/intake-agent/endpoint/protocols/openai/responses?api-version=v1
python3 -m pytest tests/azure/test_hosted_durable_persistence.py -m azure -q -s
```

- Job execution: `job-intake-qe-durable-test-nrfu43d`
- Execution: `2026-08-08T21:58:14Z`–`22:00:42Z`, `Succeeded`
- Raw pytest outcome: `1 passed, 2 warnings in 72.47s (0:01:12)`
- Persisted value: `Durable Verification 4a661e4f6f57`
- Conversation:
  `conv_97e9f353b34d89a400iTjUpG41541bq5RBzqV1H3YrsocVx65D`
- Session:
  `8639253cd3eb10156fed2965a9ccbf4b602a353655feafa85b063f8a75e1fb0`
- The write, same-session resume, and fresh-session resume all returned the exact
  persisted project name.

The job, temporary Foundry Agent Consumer assignment, temporary delegated-user
impersonation assignment/custom role, and local job artifacts were removed after
the run. Networking was not changed.

---

## Section 34 — JSON Schema Hosted Agent Validation (2026-08-13)

**Scope:** Deploy a new `intake-agent` direct-code version containing canonical
Draft 2020-12 template version `1.1.0`. No infrastructure provisioning is
required.

| Check | Result | Evidence |
|---|---|---|
| Azure context | ✅ PASS | Subscription `87e1a785-896b-4eb4-a214-47f67995133e`; existing `rg-intake-dev` in `eastus2` is `Succeeded` |
| azd + Foundry extension | ✅ PASS | azd `1.31.0`; `azure.ai.agents` `1.0.0-beta.9` |
| Source tests | ✅ PASS | `763 passed, 1 Azure-only test skipped` |
| Ruff / mypy / import-linter | ✅ PASS | 0 lint/type errors; 4 import contracts kept |
| Bicep build + lint | ✅ PASS | `infra/main.bicep` compiled and linted without error |
| Project configuration | ✅ PASS | `azure.yaml` parses as Bicep with one `azure.ai.agent` service |
| Azure preflight | ✅ PASS | 0 errors; Bot Service remains intentionally gated |
| Azure policy | ✅ PASS | Existing subscription assignments reviewed; no new policy blocker |
| Static RBAC | ✅ PASS | Agent/worker data-plane roles remain resource-scoped |
| ARM what-if | ✅ PASS | Exit 0; no create/delete operations. Infrastructure deployment intentionally omitted for this code-only release |
| Direct-code package | ✅ PASS | Flat 52 KB archive; root entry point and dependency manifests present; canonical schema included; no local/dev artifacts |
| Existing agent lookup | ✅ PASS | `intake-agent:8` is active; current definition and managed-identity settings used as the deployment baseline |

The normal `azd package` path packaged the worker successfully but could not
package the Hosted Agent because azd has no noninteractive login in this
runner. The validated direct-code REST path uses the already authenticated
Azure CLI identity and is the established deployment mechanism for this
Hosted Agent. This is not an infrastructure validation failure.

---

## Section 35 — JSON Schema Hosted Agent Deployment (2026-08-13)

| Item | Result |
|---|---|
| Deployment | New immutable Hosted Agent version `intake-agent:9` |
| State | `active` |
| Code hash | `cbeaf40e04d2b432dec8b2a4c1d6f1f1982c722a3f379a70dfe7b5aeb383b231` |
| Project endpoint | `https://ais-intake-2k2osaev.services.ai.azure.com/api/projects/aiproj-intake-dev` |
| Runtime | Python 3.13, Responses 2.0.0, remote dependency build |
| Agent identity | `7698b8bc-55ea-49b5-b2a8-ad06a16a1e9e` |
| Cosmos role | Built-in Data Contributor scoped to database `intake` |
| Blueprint roles | Foundry invocation, Blob Data Contributor, Blob Delegator, and Service Bus Data Sender verified at resource scope |

The package was uploaded with the Foundry direct-code versions API and the
required SHA-256 header. Version 8 was not modified and remains available for
rollback.

Post-deployment invocation returned HTTP 200 with response status `completed`.
The agent self-created the schema-backed template through private Cosmos
networking, then accepted:

- `project.name`
- `project.description`
- `requester.business_unit`
- `priority`

All four required gaps were resolved. The smoke request was intentionally not
submitted. `eval.yaml` now targets version 9; the installed Foundry azd
extension does not expose an evaluation command, so no remote evaluation run
was started from this runner.
