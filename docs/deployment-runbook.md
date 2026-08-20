# Intake Agent deployment runbook

## Scope

This runbook governs infrastructure preflight, provisioning, runtime publication,
rollback, secret rotation, and teardown. The development environment has been
provisioned; this does not authorize test or production promotion.

## Preflight

1. Select the subscription and sign in with both `az` and `azd`.
2. Run `./scripts/azure/preflight.ps1 -EnvironmentName <dev|test|prod> -WhatIf`.
3. Resolve every provider, permission, quota, policy, and what-if finding.
4. Confirm the deployment principal has resource creation and role-assignment authority.
5. Confirm the runner can resolve and reach private endpoints after provisioning.

## Provisioning

For an approved environment:

```powershell
azd env new <environment>
azd env set AZURE_LOCATION eastus2
azd env set AZURE_NETWORK_MODE hardened
azd env set AZURE_DEPLOY_WORKLOADS false
azd provision
```

The post-provision hook creates the dynamic private DNS zone required by the internal Container Apps environment. Verify that every data-service hostname resolves to a private IP from a VNet-connected runner.

## Runtime and Foundry publication

1. Open the ACR public endpoint only for the bounded remote-build operation, build
   each container once, resolve its digest, and restore public access disabled,
   default deny, and export disabled in a `finally` path.
2. Record immutable image digests; tags alone are not accepted.
3. Add the Hosted Agent, Prompt Agent, requester Toolbox, and reviewer Toolbox
   artifacts declared by `infra/foundry/deployables.json`.
4. Set `COMMAND_SERVICE_IMAGE`, `WORKERS_IMAGE`, `EVALUATION_IMAGE`,
   `FOUNDRY_CONFIGURATION_IMAGE`, and `HOSTED_AGENT_IMAGE` to digest-pinned
   references.
5. Set `AZURE_DEPLOY_WORKLOADS=true`, reprovision the dormant compute resources, then run `azd deploy`.
6. Run the VNet-local Foundry configuration job. It uses managed identity for ARM
   connection creation and Foundry data-plane Toolbox and agent version creation;
   it must wait for both Hosted versions to become `active`.
7. Configure tenant-governed requester/reviewer OAuth connections and validate their
   exact audience and delegated scopes.
8. Capture the actual Hosted and Prompt Agent instance principal IDs and run:

   ```powershell
   ./scripts/azure/post-publish-rbac.ps1 `
     -AgentPrincipalIds <hosted-principal>,<prompt-principal>
   ```

9. Run `scripts/foundry/smoke_live.py` from the private configuration job. Treat an
   `oauth_consent_request` as the expected pre-consent result, not a runtime failure.
10. Validate private MCP access, Toolbox consent, Search read-only access, telemetry,
    and cross-user isolation before Teams publication.

## Secret rotation

Managed identity is the default and Storage, Cosmos DB, Search, Service Bus, and ACR local authentication is disabled. For an exceptional secret:

1. Create a new Key Vault secret version through an approved privileged workflow.
2. Restart only the identity-scoped workload that consumes it.
3. Verify the new version, revoke the old credential, and retain redacted rotation evidence.
4. Never place secret values in Bicep parameters, `azd` environment files, logs, or Foundry instructions.

## Rollback

1. Repoint runtime resources to the previous approved immutable image digests.
2. Restore the previous compatible Hosted Agent, Prompt Agent, Toolbox, MCP contract, and behavior versions.
3. Do not roll back Cosmos schema or immutable request revisions destructively.
4. Run smoke, private-connectivity, authorization, and telemetry checks.
5. Record the rollback decision and deployed versions.

## Teardown

1. Export required audit and release evidence under the approved retention policy.
2. Remove Foundry agent applications, Toolboxes, connections, and capability hosts in the documented platform order.
3. Disable the production resource-group delete lock through an approved change.
4. Run `azd down --purge` only for an approved disposable environment.
5. Verify soft-deleted Key Vault and Cognitive Services resources are retained or purged according to policy.
6. Verify private DNS links, federated credentials, tenant applications, and Microsoft 365 catalog entries are removed by their owning procedures.

## Production blockers

- Final region, model deployment, quota, and data-residency approval.
- Tenant administrator approval for delegated OAuth consent and required Graph
  permissions.
- Private CI/self-hosted runner or approved VPN/jump-host path.
- Retention/deletion policy, Foundry conversation deletion evidence, recovery testing, alert thresholds, and production budgets.
- Completed end-to-end user OAuth/MCP, cross-user isolation, worker/handover,
  accessibility, and Teams publication evidence.
- Approved evaluation dataset and thresholds; release remains fail-closed while
  either approval is pending.
