# Infrastructure Configuration Outputs

Each runtime reads configuration from environment variables. No secrets are stored in config — Azure data-plane authentication uses managed identity. The Foundry custom OAuth client credential is stored only in an approved Foundry project connection/secret store, not application environment configuration.

> **ADR-015 status:** Bicep, `azure.yaml`, runtime code, and guarded deployment
> automation emit and consume the implemented values below. Tenant-scoped Entra
> applications and the secure Foundry OAuth connection/Toolbox still require
> the separately governed bootstrap and verification procedure.

## Private requester MCP target environment

| Variable | Description |
|---|---|
| `INTAKE_MCP_ENDPOINT` | Private streamable-HTTP endpoint; non-secret |
| `INTAKE_MCP_TENANT_ID` | Exact allowed Entra tenant |
| `INTAKE_MCP_ISSUER` | Exact allowed token issuer |
| `INTAKE_MCP_AUDIENCE` | MCP resource application client-ID GUID (`aud` for Entra v2 access tokens) |
| `INTAKE_MCP_REQUIRED_SCOPE` | Versioned delegated scope, initially `Intake.Tools.ReadWrite` |
| `INTAKE_MCP_TOOLBOX_SERVER_LABEL` | Exact Toolbox MCP server label used to qualify allowed tools |
| `INTAKE_MCP_CONTRACT_VERSION` | MCP/tool schema contract emitted by the server |
| `INTAKE_MCP_SUPPORTED_AGENT_RANGE` | Compatible Hosted Agent contract range |
| `AZURE_CLIENT_ID` | Dedicated MCP UAMI client ID for Azure data access |

Token signature/JWKS, issuer, `tid`, audience, lifetime, and delegated scope are
validated before `ActorContext` creation. Identity comes only from validated
`tid` and `oid`; bounded conversation/correlation/idempotency values come only
from trusted protocol metadata. There is no deployed fallback to a local or
in-process actor.

The MCP OAuth credential is deliberately absent from this table. It is managed
by the approved Foundry project connection/secret facility.

## Hosted Agent (`intake_agent`) environment

| Variable | Description | Example |
|----------|-------------|---------|
| `INTAKE_COSMOS_ENDPOINT` | Cosmos DB account URI | `https://cosmos-intake-dev.documents.azure.com:443/` |
| `INTAKE_COSMOS_DATABASE` | Database name | `intake` |
| `INTAKE_COSMOS_REQUESTS_CONTAINER` | Aggregate + audit + outbox container | `request-state` |
| `INTAKE_COSMOS_TEMPLATES_CONTAINER` | Template version container | `templates` |
| `INTAKE_COSMOS_IDEMPOTENCY_CONTAINER` | TTL command-result container | `idempotency` |
| `INTAKE_PERSISTENCE_BACKEND` | Durable request backend outside local development | `cosmos` |
| `INTAKE_BLOB_BACKEND` | Durable artifact backend outside local development | `azure` |
| `INTAKE_SERVICEBUS_BACKEND` | Durable event transport outside local development | `azure` |
| `INTAKE_SERVICEBUS_NAMESPACE` | Service Bus FQDN | `sb-intake-dev.servicebus.windows.net` |
| `INTAKE_SERVICEBUS_QUEUE` | Domain event queue name | `domain-events-durable` |
| `INTAKE_BLOB_ENDPOINT` | Blob service endpoint | `https://stintakedev.blob.core.windows.net` |
| `INTAKE_BLOB_CONTAINER_ARTIFACTS` | Versioned artifact container | `request-artifacts` |
| `INTAKE_SEARCH_ENDPOINT` | AI Search endpoint | `https://search-intake-dev.search.windows.net` |
| `INTAKE_SEARCH_INDEX` | Knowledge index name | `enterprise-knowledge` |
| `INTAKE_APPINSIGHTS_CONNECTION` | App Insights connection string | `InstrumentationKey=...` |
| `INTAKE_TEMPLATE_ID` | Default template ID (POC) | `general-intake-v1` |
| `INTAKE_ENVIRONMENT` | Environment name | `dev` / `test` / `prod` |
| `AZURE_CLIENT_ID` | User-assigned managed identity client ID | (UUID) |

## Workers (`intake_workers`) environment

| Variable | Description |
|----------|-------------|
| `INTAKE_COSMOS_ENDPOINT` | Same Cosmos endpoint |
| `INTAKE_COSMOS_DATABASE` | Same database |
| `INTAKE_COSMOS_REQUESTS_CONTAINER` | `request-state` |
| `INTAKE_COSMOS_TEMPLATES_CONTAINER` | `templates` |
| `INTAKE_COSMOS_IDEMPOTENCY_CONTAINER` | `idempotency` |
| `INTAKE_SERVICEBUS_NAMESPACE__fullyQualifiedNamespace` | Service Bus identity-based connection (FQDN) |
| `INTAKE_SERVICEBUS_NAMESPACE__credential` | Must be `managedidentity` for identity-based auth |
| `INTAKE_SERVICEBUS_NAMESPACE__clientId` | Worker user-assigned identity client ID (for scale controller) |
| `INTAKE_SERVICEBUS_QUEUE` | `domain-events-durable` |
| `INTAKE_BLOB_ENDPOINT` | Blob storage endpoint |
| `INTAKE_BLOB_CONTAINER_ARTIFACTS` | Artifact container name (`request-artifacts`) |
| `INTAKE_KEYVAULT_URI` | Key Vault URI (for non-Entra downstream creds) |
| `INTAKE_APPINSIGHTS_CONNECTION` | App Insights connection string |
| `INTAKE_ENVIRONMENT` | Environment name |
| `AZURE_CLIENT_ID` | Worker managed identity client ID |

## Required Cosmos data-plane shape

| Container | Partition key | TTL | Required records |
|-----------|---------------|-----|------------------|
| Configured request-state container (`request-state` in the deployed environment) | `/requestId` | disabled (`-1`) | request projection, revision, workflow event, outbox |
| `templates` | `/templateId` | disabled (`-1`) | immutable `version:{version}` documents |
| `idempotency` | `/scopeId` | enabled for item-level TTL (`-1`) | command key/result documents |

The configured request-state container's `/requestId` partition key is
non-negotiable: Cosmos transactional batches cannot span partitions, and the
application atomically commits projection, revision, audit event, and outbox.
Physical names are configuration, not adapter constants. The deployed
environment uses `request-state` because the retained legacy `requests`
container has immutable partition key `/tenantId`; it must not be destructively
recreated. On first use, the Hosted Agent idempotently seeds its packaged
canonical template through managed identity. Its document ID is
`version:{version}`; it must have
`docType=templateVersion`, `templateId`, `version`, `displayName`,
`jsonSchema`, `qualityThreshold`, `isActive`, and `createdAt`. `jsonSchema` is
the canonical Draft 2020-12 request contract. The envelope duplicates only the
metadata required for Cosmos lookup and active-version selection, and must
match the schema's `title` and root `x-intake` metadata.

The current `general-intake-v1` schema version is `1.1.0`. Templates are
authored in `src/intake_domain/template_schemas/` and seeded from the packaged
schema. The runtime does not support the superseded `fields[]` document shape.

The deployed outbox destination is `domain-events-durable`. It has duplicate
detection enabled and is selected through `INTAKE_SERVICEBUS_QUEUE`. The legacy
`domain-events` queue is retained because duplicate detection cannot be enabled
in place; application code must not hard-code either physical queue name.

## Required managed-identity data-plane roles

| Runtime identity | Resource scope | Role |
|------------------|----------------|------|
| Requester MCP UAMI | Cosmos `/dbs/intake` | Cosmos DB Built-in Data Contributor |
| Requester MCP UAMI | `domain-events-durable` queue | Azure Service Bus Data Sender |
| Requester MCP UAMI | `request-artifacts` container | Storage Blob Data Contributor |
| Artifact-writing runtime UAMI | `request-artifacts` container | Storage Blob Data Contributor |
| Artifact URL-signing runtime UAMI | Storage account | Storage Blob Delegator |
| Worker UAMI | Cosmos `/dbs/intake` | Cosmos DB Built-in Data Contributor |
| Worker dispatcher UAMI | `domain-events-durable` queue | Azure Service Bus Data Sender |
| Trigger/scale-controller UAMI | Required queues or namespace | Azure Service Bus Data Receiver; retain Data Owner only where FC1 queue-depth scaling requires its management read actions |

Blob data access and delegation are deliberately split: Storage Blob Data
Contributor is scoped to `request-artifacts`, while account-scoped Storage Blob
Delegator supplies `generateUserDelegationKey` for short-lived URLs. Granting
Storage Blob Data Contributor at account scope is broader than required. No
account keys, Cosmos keys, Service Bus SAS policies, or storage connection
strings are accepted.

Every non-local runtime must set `AZURE_CLIENT_ID` to its user-assigned managed
identity client ID. The worker dispatcher accepts either
`INTAKE_SERVICEBUS_NAMESPACE` or the Functions identity-binding setting
`INTAKE_SERVICEBUS_NAMESPACE__fullyQualifiedNamespace`.

The steady-state template grants requester data access only to the MCP UAMI.
Upgraded environments can retain legacy Hosted Agent role assignments because
incremental ARM deployments do not delete them. The guarded postdeploy cutover
removes those assignments only after delegated-user verification and explicit
`MCP_DATA_PLANE_CUTOVER_APPROVED=true`; then negatively verify the Hosted Agent
cannot read or write requester stores. Worker identities and roles do not
change. The delegated user token never authenticates to these Azure resources.

## Worker deployment package contract

The Functions deployment root must contain:

```text
function_app.py
host.json
requirements.txt
intake_domain/
intake_persistence/
```

`requirements.txt` must install `azure-functions`, `azure-cosmos>=4.7`,
`azure-servicebus>=7.12`, `azure-identity>=1.17`, `pydantic>=2.7`, and
`aiohttp>=3.9`. Pydantic is imported by the domain package; aiohttp provides the
async transport required by Azure Identity in the Functions package. The
current worker imports `intake_persistence.cosmos`,
`intake_persistence.servicebus`, and their `intake_domain` dependencies at
module load. Therefore a source-only archive of `src/intake_workers/` is
invalid: the `azure.yaml` prepackage hook stages `src/intake_domain/` and
`src/intake_persistence/` beside `function_app.py`, and the postpackage hook
removes the staged copies. The private Python 3.11 runner installs dependencies
under `.python_packages/lib/site-packages` before creating the FC1 archive. Do
not copy `intake_agent`, test/evaluation packages, local in-memory state,
credentials, or `.env` files.

## Evaluation job environment

| Variable | Description |
|----------|-------------|
| `INTAKE_EVAL_STORAGE_ENDPOINT` | Evaluation storage account endpoint |
| `INTAKE_EVAL_CONTAINER` | Dataset/evidence container |
| `INTAKE_AGENT_ENDPOINT` | Foundry agent endpoint for test invocations |
| `INTAKE_APPINSIGHTS_CONNECTION` | App Insights connection string |
| `AZURE_CLIENT_ID` | Eval job managed identity client ID |

## Bicep outputs → azd environment mapping

Bicep `main.bicep` outputs these values. `azure.yaml` maps them to service environment variables:

```yaml
# azure.yaml service config pattern
services:
  agent:
    host: foundry
    project: src/intake_agent
    env:
      INTAKE_COSMOS_ENDPOINT: ${AZURE_COSMOS_ENDPOINT}
      INTAKE_COSMOS_DATABASE: ${AZURE_COSMOS_DATABASE}
      INTAKE_SERVICEBUS_NAMESPACE: ${AZURE_SERVICEBUS_NAMESPACE}
      # ...
  workers:
    host: function
    project: src/intake_workers
    env:
      INTAKE_COSMOS_ENDPOINT: ${AZURE_COSMOS_ENDPOINT}
      # ...
```

For ADR-015, resource-group-scoped Bicep may emit only non-secret Azure resource
configuration such as the private endpoint, MCP UAMI client ID, and deployed
contract/image version. Entra application registrations, service principals,
delegated scopes, preauthorization, redirect URIs, and consent grants are
tenant-scoped and are not Bicep outputs. A separately governed, idempotent
procedure must configure and evidence them. Until executable automation exists,
do not claim `azd provision` performs this setup.

## Local development overrides

For local testing without Azure resources:

| Variable | Local value |
|----------|-------------|
| `INTAKE_PERSISTENCE_BACKEND` | `inmemory` |
| `INTAKE_SERVICEBUS_BACKEND` | `inmemory` |
| `INTAKE_BLOB_BACKEND` | `inmemory` |

When `*_BACKEND=inmemory`, the composition root injects in-memory repository
implementations only when `INTAKE_ENVIRONMENT=local`. Hosted dev, test, staging,
and production fail startup rather than falling back to ephemeral state.
