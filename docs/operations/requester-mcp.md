# Private Requester MCP Operations Runbook

> **Implementation status (2026-08-19):** the MCP runtime, internal Container
> App, workload identity/RBAC, hosted Toolbox client, Entra bootstrap scripts,
> and guarded deployment checks are implemented. The secure Foundry OAuth
> connection/Toolbox, delegated-user consent verification, and final RBAC
> cutover remain environment-specific operator gates. Do not route production
> traffic until every cutover gate below has evidence.

## Runtime and trust boundaries

```text
Requester
  -> Foundry Agent/Toolbox (per-user consent and token refresh)
  -> private streamable-HTTP MCP Container App (delegated token validation)
  -> deterministic intake application/domain
  -> Cosmos DB / Blob / Service Bus (MCP managed identity)
```

The MCP app uses internal ingress in the existing VNet-integrated Container Apps
managed environment. The delegated user token stops at the MCP authorization
boundary. A dedicated MCP user-assigned managed identity accesses Azure data
services. The Hosted Agent identity accesses Foundry/Toolbox and must not retain
requester data-plane roles after cutover.

Production exposes only `get_intake_context`, `update_intake_field`,
`submit_intake_for_review`, and `list_my_intake_requests`. The local FastAPI
service, DevUI, and in-process adapter are development paths, not production
fallbacks.

## Provisioning responsibility

### Tenant-scoped Entra setup

An Entra/Foundry administrator must create or approve, in the Foundry project's
tenant:

1. the single-tenant MCP resource application;
2. the versioned delegated `Intake.Tools.ReadWrite` scope;
3. the OAuth client used by the Foundry project connection;
4. the exact redirect URI required by the selected Foundry connection flow;
5. client preauthorization where policy selects it;
6. tenant/admin consent and end-user consent policy; and
7. the least-privilege Foundry Agent Consumer assignments.

Application registrations, service principals, scopes, redirect URIs,
preauthorization, and consent grants are tenant-scoped. They are outside
resource-group-scoped Bicep. Use a separately reviewed, idempotent setup
procedure when one is implemented; until then, record manual setup evidence.
Never place an OAuth client credential in source control, normal logs, Bicep
outputs, or azd environment output. Store it only in an approved secret store or
Foundry project connection.

The requester, application registrations, and Foundry project must be in the
same tenant. Cross-tenant token exchange is not supported by this design.

### Resource-group-scoped Azure setup

Bicep is expected to own:

- the internal-ingress MCP Container App in the existing managed environment;
- private DNS/reachability, probes, scaling, revision settings, and diagnostics;
- the MCP user-assigned managed identity;
- least-privilege Cosmos, Blob, and Service Bus data-plane roles; and
- non-secret endpoint, audience, scope, image, identity, and version mappings.

Bicep does not grant tenant consent or create the tenant application objects.
Do not claim `azd provision` completes the Entra/Foundry setup unless executable
automation and verification are added later.

## Foundry connection and Toolbox

Create a versioned Foundry project connection using custom OAuth, store its
credential in the approved connection/secret facility, and point it at the
single-tenant MCP resource audience and delegated scope. Create a versioned
Toolbox that selects the private MCP connection and the approved MCP/tool
contract range. Set the Toolbox MCP server label to the exact
`MCP_TOOLBOX_SERVER_LABEL` value; Toolbox exposes each MCP tool as
`{server_label}.{tool_name}`, and the Hosted Agent allowlist uses those qualified
names. Configure the Hosted Agent to consume that Toolbox with its workload
identity.

First use may return `consent_required`. Direct the user through the approved
interactive consent experience. Never retry with app-only authentication,
another user's token, a Microsoft-resource token, or a shared identity.

## Pre-deployment checklist

- [ ] Foundry, users, MCP resource app, OAuth client, and consent are in one tenant.
- [ ] Redirect URI, v2 token GUID audience, issuer/tenant, and delegated scope exactly match runtime configuration.
- [ ] Toolbox MCP server label exactly matches `MCP_TOOLBOX_SERVER_LABEL`.
- [ ] OAuth secret exists only in the approved Foundry connection/secret store.
- [ ] MCP image is immutable/pinned and contract/domain versions are recorded.
- [ ] Internal ingress has no public route; private DNS resolves from the Foundry network path.
- [ ] MCP identity has only required data-plane roles.
- [ ] Hosted Agent requester data-plane roles are scheduled for removal at cutover.
- [ ] Hosted Agent and MCP supported contract ranges overlap.
- [ ] Startup configuration fails closed when any security setting is absent.
- [ ] Rollback revisions and the previous compatible Toolbox selection are retained.

## Cutover and verification

1. Deploy the MCP revision without routing requester tools to it.
2. Verify liveness, readiness, private DNS, TLS, and Foundry-to-MCP reachability.
3. Verify Toolbox discovery returns exactly the four approved tools and schemas.
4. Test valid user consent and invocation in the target tenant.
5. Prove rejection for wrong signature, issuer, tenant, audience, scope, expiry,
   not-before, app-only token, and caller-supplied identity/context.
6. Execute all four tools end to end. Replay mutations with the same
   idempotency key and prove one business effect.
7. Verify timeout, cancellation, unavailable MCP, and consent-required behavior.
8. Verify logs/traces contain correlation and version fields but no bearer
   token, OAuth secret, or sensitive payload.
9. Select the new Toolbox/agent release under the normal approval gate.
10. Record the approved cutover evidence, set
    `MCP_DATA_PLANE_CUTOVER_APPROVED=true`, rerun the MCP postdeploy cutover
    script, and prove the Hosted Agent can no longer access data resources
    directly. Without that explicit approval, deployment retains any legacy
    assignments rather than removing them prematurely.

Absence of any evidence blocks production cutover. There is no silent fallback.

## Routine operations

Monitor:

- Container App readiness, restart count, replica saturation, latency, error and
  timeout rates;
- OAuth consent-required and token-validation failure rates by reason, without
  token or PII logging;
- private DNS/TLS failures and Foundry/Toolbox discovery failures;
- operation success/conflict/idempotent-replay rates;
- Cosmos, Blob, and Service Bus authorization failures for the MCP identity; and
- agent, Toolbox, MCP image, tool contract, domain, template, and schema version
  compatibility.

Alert on sustained readiness failure, public ingress drift, repeated invalid
audience/issuer/tenant, authorization spikes, contract incompatibility, data
identity RBAC drift, token/secret detection in telemetry, or mutation ambiguity.

## Troubleshooting

| Symptom | Checks and action |
|---|---|
| `consent_required` | Confirm user and Foundry project share a tenant, the connection uses the approved OAuth client/scope, and tenant policy permits consent. Complete the approved interactive flow; do not use workload identity as the user. |
| `401` invalid token | Compare issuer, `tid`, audience, signature/JWKS, lifetime, and delegated scope. Do not weaken validation. |
| `403` authorized identity, denied operation | Confirm requester product policy/ownership and scope. Caller-supplied roles or request IDs are never accepted. |
| Toolbox cannot discover tools | Check selected Toolbox/connection version, MCP readiness, private DNS/TLS, internal ingress, and Foundry private-network path. Do not enable public ingress. |
| MCP can authenticate but data calls fail | Check `AZURE_CLIENT_ID` selects the MCP UAMI and its narrowly scoped Cosmos/Blob/Service Bus roles. Do not forward the user token. |
| Mutation timed out | Reload authoritative context before deciding whether to replay. Replay only with the same idempotency key; never invent a second key. |
| Contract mismatch | Stop rollout and select an overlapping Hosted Agent/MCP contract pair. Do not reinterpret an incompatible schema in the prompt. |
| Hosted Agent still accesses data directly | Treat as RBAC drift; remove its requester data-plane roles and repeat negative-access verification. |
| Local adapter appears active when deployed | Stop requester traffic. Deployed environments must fail startup rather than use local/in-process behavior. |

## Rollback

Prefer a forward fix. Otherwise, under the deployment approval gate:

1. stop new requester mutations if the outcome of in-flight writes is unknown;
2. select the last known-good, mutually compatible Hosted Agent, Toolbox, and
   MCP image/revision;
3. verify private reachability, consent, contract overlap, identity separation,
   and all four operations;
4. reconcile timed-out mutations using their original idempotency keys; and
5. retain durable data and audit evidence.

Do not use resource-group teardown, public ingress, token-validation bypass, or
automatic in-process fallback. The one-release local adapter is allowed only in
local tests/DevUI and an explicitly reviewed release rollback; it must remain
unselectable in a deployed environment.

## Ownership and escalation

| Incident | Primary | Required partners |
|---|---|---|
| Tool/domain behavior | Trinity | Morpheus, Switch |
| Contract/version compatibility | Morpheus | Trinity, Switch |
| Container Apps, network, identity, RBAC, deployment | Tank | Azure platform/on-call |
| OAuth, tenant consent, Toolbox user experience | Neo | Tank, Entra/Foundry administrator |
| Security/token/secret event | Security/identity owner | Tank, Morpheus, service owner |
| Test or release evidence gap | Switch | Owning implementer |

The service owner/on-call coordinates the incident and user communication.
Security-significant token validation or credential events follow the
organization's security incident process.
