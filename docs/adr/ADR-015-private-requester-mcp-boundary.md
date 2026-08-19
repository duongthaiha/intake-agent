# ADR-015: Private MCP Boundary for Requester Tools

**Status:** Accepted  
**Date:** 2026-08-19  
**Deciders:** Morpheus, Ha Duong  
**Supersedes:** ADR-003 and ADR-009 for the requester tool boundary only  
**Preserves:** ADR-010

## Context

The Hosted Agent currently composes the four requester operations in-process.
A second reusable consumer boundary is now required, so the extraction condition
in ADR-009 has been met. Keeping the model-facing host as the data-access
workload would also mix delegated user authorization with Azure data-plane
authorization.

This decision is intentionally narrow. The deterministic domain package,
workers, review commands, and downstream commands remain governed by their
existing decisions. In particular, ADR-010 remains in force: the private,
versioned `intake-domain` package is the authoritative deterministic core and is
bundled into every state-changing runtime that needs it.

## Decision

### Boundary and hosting

A private, streamable-HTTP MCP server will expose exactly:

- `get_intake_context`
- `update_intake_field`
- `submit_intake_for_review`
- `list_my_intake_requests`

It will run as a separate Azure Container App in the **existing** VNet-integrated
Container Apps managed environment. Ingress is internal only. Private DNS and
the Foundry private-network path must resolve and reach the endpoint before
cutover. The local FastAPI application is not this boundary and must not be
published as a production substitute. Reviewer, administrator, worker, generic
HTTP, arbitrary URL, and repository operations are not exposed through this
MCP server.

The Hosted Agent consumes a pinned, versioned Microsoft Foundry Toolbox whose
MCP connection targets this private endpoint. The Hosted Agent authenticates to
Foundry with its workload identity and the `https://ai.azure.com/.default`
scope. The Toolbox owns the custom OAuth connection, user consent, delegated
token acquisition and refresh, and selected MCP/tool version. Hosted code does
not handle an OAuth client secret or forward a Microsoft-resource token to the
custom endpoint.

### Identity and authorization

The MCP server is protected by a single-tenant Microsoft Entra application
registration with a versioned delegated scope initially named
`Intake.Tools.ReadWrite`. Custom OAuth identity passthrough is required.

For every invocation, the MCP authentication boundary must:

1. validate the token signature against trusted tenant metadata;
2. validate the exact issuer and tenant (`tid`);
3. validate the MCP application audience;
4. validate lifetime, including expiry and not-before;
5. require the configured delegated scope; and
6. reject app-only, cross-tenant, malformed, or ambiguous identities.

Only after all checks pass may immutable claims be mapped to `ActorContext`:

| `ActorContext` value | Trusted source |
|---|---|
| tenant identity | validated `tid` |
| represented user identity | validated `oid`, namespaced by `tid` |
| role | fixed requester capability plus deterministic product policy; never a model or caller claim |
| workload identity | authenticated MCP Container App identity |
| conversation/correlation/idempotency context | trusted Toolbox/MCP protocol metadata validated against the operation contract |

Display names, email addresses, arbitrary group text, tool arguments, headers
not established by the trusted proxy contract, and model output are not identity
sources. Tool arguments must not contain user IDs, tenant IDs, roles,
authorization results, arbitrary request IDs, correlation IDs, or idempotency
IDs. Missing or conflicting trusted context fails closed. Production has no
shared-user, platform-isolation, local-user, or in-process identity fallback.

The delegated token authorizes the product operation only. It is never sent to
Cosmos DB, Blob Storage, Service Bus, Key Vault, or another downstream service.
A separate MCP user-assigned managed identity authenticates to those services
with least-privilege data-plane roles. After cutover, the Hosted Agent identity
retains only the permissions needed for Foundry/Toolbox consumption; requester
data-plane roles move to the MCP identity. Worker identities remain separate.

### Tenant and consent constraints

- The user, MCP app registration, OAuth client/connection, and Foundry project
  must be in the same Entra tenant. Cross-tenant exchange is unsupported.
- An administrator must create/approve the tenant application objects,
  delegated permission, client preauthorization where selected, redirect URI,
  and tenant consent policy.
- End users receive only the least-privilege Foundry Agent Consumer access.
  First use can require an interactive consent flow; consent-required is an
  explicit user-facing state, not an anonymous or workload-identity fallback.
- OAuth credentials are stored only in an approved secret store or Foundry
  project connection. They are never committed, logged, or emitted as Bicep or
  azd outputs.

Entra application registrations, service principals, delegated scopes,
preauthorization, redirect URIs, and consent grants are **tenant-scoped**
objects. Resource-group-scoped Bicep does not create or own them. Any
provisioning procedure for these objects must be separately governed,
idempotent, non-interactive when used by automation, and produce redacted
evidence. Until that procedure is implemented and verified, setup is manual.
Bicep remains responsible only for resource-group resources such as Container
Apps, managed identities, networking, diagnostics, and Azure RBAC.

### Contracts and versioning

- Tool names are stable within a major MCP contract version.
- Request, result, operation-context, and error schemas are transport-neutral,
  closed to unknown properties, bounded, and independently versioned.
- Additive optional fields require a minor version. Removal, rename, changed
  meaning, tighter previously-valid constraints, or error semantic changes
  require a new major version/tool surface.
- Mutations require a trusted idempotency key and expected revision. Reads may
  be retried; mutations are retried only by replaying the same idempotency key.
- Errors preserve validation, authorization, not-found, conflict,
  consent-required, transient, timeout, and permanent categories.
- Hosted Agent and MCP releases advertise their supported contract ranges.
  Deployment is blocked unless the ranges overlap.
- Maintain at least the current and immediately previous compatible minor
  contract during the rollout window. Major versions are parallel tools or
  Toolboxes, never an in-place semantic replacement.
- Telemetry records agent, Toolbox, MCP image, tool contract, domain package,
  template, and schema versions without recording bearer tokens or sensitive
  tool payloads.

### Reliability and production behavior

The service has bounded request/tool timeouts, cancellation propagation,
readiness and liveness probes, autoscaling limits, revision controls,
structured/redacted telemetry, and server-side mutation idempotency. Startup
fails if tenant, issuer, audience, scope, endpoint, workload identity, or durable
backend configuration is incomplete.

If Toolbox, OAuth, private DNS, MCP readiness, or token validation is
unavailable, the production request fails explicitly. There is no silent direct
tool, local API, or in-process fallback. A local in-process adapter may remain
for one release for tests, DevUI, and an operator-controlled rollback of the
Hosted Agent deployment, but it must be impossible to select in a deployed
environment.

## Deployment prerequisites

Cutover requires evidence that:

1. the Container App is in the existing managed environment with internal
   ingress, private DNS, health probes, diagnostics, and a pinned image digest;
2. Foundry can reach the private MCP endpoint and Toolbox discovery returns only
   the four approved tools;
3. tenant-scoped Entra setup and admin consent are complete;
4. wrong issuer, tenant, audience, scope, signature, lifetime, and app-only
   tokens fail;
5. MCP and Hosted Agent workload identities have the intended separated RBAC;
6. all four operations pass end-to-end with user identity passthrough;
7. idempotency, timeout, unavailable-server, consent-required, and telemetry
   redaction checks pass; and
8. the Hosted Agent and MCP contract ranges overlap.

Documentation is not evidence that any prerequisite is automated or deployed.
The current implementation status must be checked in the deployment runbook and
post-deploy verification output.

## Rollback

Prefer a forward fix. If rollback is required, redeploy the last known-good
Hosted Agent, Toolbox selection, MCP image revision, and compatible contract as
one reviewed release. Keep durable data and domain schema forward-compatible;
do not tear down the resource group or revoke the MCP identity while in-flight
work remains.

The one-release local adapter is a development and controlled release rollback
mechanism only. It cannot activate automatically, cannot bypass consent, and
cannot be selected in production configuration. If the known-good private path
cannot be restored, stop requester mutations and communicate the outage.

## Operations and ownership

| Area | Accountable owner |
|---|---|
| Boundary, contracts, compatibility, production gate | Morpheus |
| MCP application/domain composition | Trinity |
| Foundry/Teams consent experience and user messaging | Neo |
| Container Apps, Entra setup procedure, identities, RBAC, networking, deployment, monitoring | Tank |
| Contract, security, resilience, and end-to-end release evidence | Switch |
| Tenant consent and application approval | Entra/tenant administrator |
| Incident coordination | Service owner/on-call; security incidents also engage the security/identity owner |

See
[`docs/operations/requester-mcp.md`](../operations/requester-mcp.md) for
prerequisites, release, rollback, operations, and troubleshooting.

## Consequences

- Requester tools gain a reusable, independently deployable trust boundary.
- Delegated user authorization and Azure data access are attributable and
  separated.
- A private network hop, Toolbox dependency, consent lifecycle, second workload
  identity, and compatibility window become operational responsibilities.
- ADR-003 and ADR-009 no longer apply to physical co-location of the four
  requester tools. They continue to describe the original rationale and all
  unaffected boundaries.
- ADR-010 remains accepted without modification.
