# ADR-015: Side-by-side Prompt Agent through a private MCP boundary

## Status

Accepted.

## Context

The production `intake-agent` is a Python Hosted Agent. Its in-process tools
derive actor scope from Foundry platform isolation and call deterministic domain
handlers. A Foundry Prompt Agent cannot run that Python code, and a remote tool
call does not provide the Hosted Agent's opaque conversation identity.

Moving validation, authorization, or lifecycle behavior into a prompt would
violate the solution's deterministic-core principle. Accepting caller-selected
request IDs without ownership checks would also create an insecure direct object
reference.

## Decision

Deploy `prompt-intake-agent` as a project-level Prompt Agent in the existing
Foundry project and on the existing `gpt-5-nano` model deployment.

The prompt agent calls four allow-listed requester tools on a separate internal
Azure Container Apps MCP service:

- `get_intake_context`
- `update_intake_field`
- `submit_intake_for_review`
- `list_my_intake_requests`

The MCP service:

- uses delegated same-tenant Entra identity through a `user-entra-token`
  project connection;
- validates token signature, issuer, audience, expiry, scope, `oid`, and `tid`;
- derives requester identity only from verified claims;
- reuses `IntakeApplication`, domain handlers, and durable adapters;
- requires explicit new-request creation and opaque request IDs for remote
  resume; and
- enforces tenant/requester ownership before request access or idempotent replay.

The Hosted Agent remains unchanged and remains the production baseline. The two
surfaces intentionally maintain separate user identity namespaces; there is no
automatic cross-surface request linking.

## Consequences

- A private MCP Container Apps environment, subnet, DNS zone, workload identity,
  image, and Entra API registration are added.
- Each user completes delegated consent once. A manual two-user isolation test
  remains a release gate because CI cannot perform interactive user consent.
- Prompt-agent versions and evaluation recipes are immutable and recorded
  independently from Hosted Agent versions.
- ADR-002 and ADR-003 remain accepted for the production Hosted Agent. This ADR
  adds a comparison path; it does not replace the modular-monolith decision.
