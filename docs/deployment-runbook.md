# Intake Agent deployment runbook

## Scope

This runbook governs infrastructure preflight, future provisioning, runtime publication, rollback, secret rotation, and teardown. It does not authorize a deployment. The current branch must not be provisioned until runtime artifacts, tenant configuration, regional quota, and private runner connectivity are approved.

## Preflight

1. Select the subscription and sign in with both `az` and `azd`.
2. Run `./scripts/azure/preflight.ps1 -EnvironmentName <dev|test|prod> -WhatIf`.
3. Resolve every provider, permission, quota, policy, and what-if finding.
4. Confirm the deployment principal has resource creation and role-assignment authority.
5. Confirm the runner can resolve and reach private endpoints after provisioning.

## Provisioning

When the deployment hold is removed:

```powershell
azd env new <environment>
azd env set AZURE_LOCATION eastus2
azd env set AZURE_NETWORK_MODE hardened
azd env set AZURE_DEPLOY_WORKLOADS false
azd provision
```

The post-provision hook creates the dynamic private DNS zone required by the internal Container Apps environment. Verify that every data-service hostname resolves to a private IP from a VNet-connected runner.

## Runtime and Foundry publication

1. Build each container once and publish it to the private ACR.
2. Record immutable image digests; tags alone are not accepted.
3. Add the Hosted Agent, Prompt Agent, requester Toolbox, and reviewer Toolbox artifacts declared by `infra/foundry/deployables.json`.
4. Set `COMMAND_SERVICE_IMAGE`, `WORKERS_IMAGE`, and `EVALUATION_IMAGE` to digest-pinned references.
5. Set `AZURE_DEPLOY_WORKLOADS=true`, reprovision the dormant compute resources, then run `azd deploy`.
6. Configure tenant-governed requester/reviewer OAuth connections and validate their exact audience and delegated scopes.
7. Capture the actual hosted and prompt agent instance principal IDs and run:

   ```powershell
   ./scripts/azure/post-publish-rbac.ps1 `
     -AgentPrincipalIds <hosted-principal>,<prompt-principal>
   ```

8. Validate private MCP access, Toolbox consent, Search read-only access, telemetry, and cross-user isolation before Teams publication.

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
- Runtime images and Foundry configuration artifacts.
- Entra application registrations, requester/reviewer delegated scopes, admin consent, and Graph permissions.
- Private CI/self-hosted runner or approved VPN/jump-host path.
- Retention/deletion policy, Foundry conversation deletion evidence, recovery testing, alert thresholds, and production budgets.
- End-to-end capability evidence for both agent variants and Teams publication.
