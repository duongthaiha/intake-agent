# CI/CD Operator Runbook — `dev` deployment pipeline

> **Current status (2026-08-19):** the workflow, Bicep, and runner bootstrap
> implementation exists in this branch. The GitHub `dev` Environment now has a
> required reviewer and a `main`-only deployment policy, but branch protection,
> Azure-backed variables/OIDC roles, and the runner bootstrap are still pending.
> Until an operator completes and validates those items, the deploy workflow is
> not operational. `test` and `prod` remain unconfigured and out of scope.
>
> ADR-015's private requester MCP Container App, separate workload identity,
> runtime, and guarded deployment automation are implemented. Tenant-scoped
> Entra objects and the secure Foundry OAuth connection/Toolbox remain a
> separately governed bootstrap. Follow
> [the requester MCP runbook](requester-mcp.md); production cutover is blocked
> until its delegated-user gates have evidence.

## Architecture and trust boundaries

The steady-state template, [`infra/main.bicep`](../../infra/main.bicep), is
resource-group scoped. It deploys application infrastructure into the existing
`rg-intake-dev` resource group and deliberately excludes all runner resources.
Runner infrastructure is created or updated only through
[`scripts/azure/bootstrap-runner.sh`](../../scripts/azure/bootstrap-runner.sh),
which invokes
[`infra/bootstrap-runner.bicep`](../../infra/bootstrap-runner.bicep) out of
band.

Private-network provisioning, Functions deployment, Foundry Hosted Agent
deployment, and live verification run on a repository-scoped, ephemeral Azure
Container Apps Jobs runner labeled `aca-intake-dev`. The runner registers with
`--ephemeral`, accepts one labeled job, and is removed after it finishes. The
job scales to zero between runs.

The two identities have separate responsibilities:

| Identity | Authentication | Permissions |
|---|---|---|
| Azure deployer | GitHub OIDC workload identity federation | Resource-group-scoped deployment/RBAC permissions |
| Runner user-assigned managed identity | Azure managed identity | `AcrPull` on the runner ACR only |

The target MCP runtime adds another identity with a separate purpose: Azure
requester data-plane access. It is not the runner or deployer identity. The
delegated user token authorizes the MCP operation and must not be forwarded to
Cosmos, Blob, or Service Bus.

The runner managed identity is not a deployment identity and has no application
data-plane or Key Vault access. The workflow obtains Azure access only through
OIDC. No Azure client secret is stored.

The fine-grained GitHub PAT used to mint a short-lived runner registration
token is passed as a secure Bicep parameter and stored directly as the ACA Job
secret `github-pat`. It is not stored in Key Vault, GitHub Actions secrets, the
repository, or an `.env` file. The bootstrap entrypoint then replaces PID 1
with a clean allow-listed environment before the runner starts; the PAT cannot
remain readable through `/proc/1/environ`. The registration token crosses that
boundary through a private temporary file that is deleted before `run.sh`.

A root-owned `ACTIONS_RUNNER_HOOK_JOB_STARTED` admission hook runs before every
workflow step. It rejects jobs unless the server-provided context identifies
this repository's `deploy.yml` on `refs/heads/main` and the event is
`workflow_run` or `workflow_dispatch`. The all-external fork approval policy
remains required as a separate repository-level control.

## Required tooling and settings

The operator workstation used for bootstrap needs Azure CLI, Bicep through
Azure CLI, Azure Developer CLI, Git, and access to the target subscription.
The deployment workflow uses the SHA-pinned `Azure/setup-azd` v2 action and
installs the `microsoft.foundry` azd extension explicitly. `azure.yaml` also
declares the required Foundry extension versions.

The Entra resource application, OAuth client, delegated scope, redirect URI,
preauthorization, tenant/admin consent, Foundry project connection, and Toolbox
are tenant/Foundry-scoped setup. Resource-group-scoped Bicep cannot own them.
Any later automation must be separately governed, idempotent, non-interactive,
and redact credentials. Until it exists, operators must not describe
`azd provision` or this workflow as end-to-end MCP/consent provisioning.

### Required GitHub variables

Configure these as `dev` Environment variables (or repository variables where
the organization deliberately centralizes non-secret settings):

| Name | Meaning |
|---|---|
| `AZURE_CLIENT_ID` | Application/client ID of the OIDC-federated Entra deployer |
| `AZURE_TENANT_ID` | Entra tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Target `dev` subscription ID |
| `AZURE_ENV_NAME` | Must be `dev` |
| `AZURE_LOCATION` | Azure region for `dev` |
| `AZURE_PRINCIPAL_ID` | **Object ID** of the deployer's service principal, not its application/client ID |

`AZURE_CLIENT_ID` and `AZURE_PRINCIPAL_ID` identify different properties of
the same deployer. The client ID is used for OIDC login; the service-principal
object ID is passed to Bicep and RBAC preflight checks.

`AZURE_RESOURCE_GROUP` is not a configurable GitHub variable. The workflow
fixes it to `rg-intake-dev`; the existing resource group is the steady-state
deployment scope. During an operator bootstrap shell, set it explicitly to the
same value so the helper script cannot target a different group.

GitHub Actions has no Azure credential secret and no runner PAT secret.

## One-time setup: foundation and runner bootstrap

These steps require Azure and GitHub administration and occur outside the
steady-state workflow.

### 1. Create the deploy identity and federated credential

Create or reuse an Entra application/service principal, grant only the
documented deployment roles at the existing `rg-intake-dev` resource-group
scope, and add a federated credential with:

```text
Issuer:   https://token.actions.githubusercontent.com
Subject:  repo:<owner>/<repository>:environment:dev
Audience: api://AzureADTokenExchange
```

This repository currently uses GitHub's **plain environment-scoped subject**
shown above. If GitHub immutable OIDC subjects are enabled later, the emitted
subject changes; update the Entra federated credential to the new exact subject
at the same time or token exchange will fail. Do not enable immutable subjects
as an isolated repository setting change.

### 2. Configure GitHub controls

1. Protect `main`: require a pull request, the `Required Checks` CI status, and
   disallow direct pushes.
2. Create the `dev` GitHub Environment, restrict it to `main`, and configure a
   required reviewer.
3. Set the repository Actions fork pull-request contributor approval policy to
   **all external contributors**. This is a required bootstrap control for the
   repository-scoped self-hosted runner. Before approving an external
   contributor's workflow, review every workflow-file change, especially any
   `runs-on` label that could select a self-hosted runner such as
   `aca-intake-dev`.
4. Add every variable in the table above.
5. Do not create `test` or `prod` environments for this pipeline.

### 3. Prepare bootstrap inputs

Authenticate Azure CLI and azd, select `dev`, and provide these values to the
bootstrap process without committing them:

| Shell input | Purpose |
|---|---|
| `AZURE_SUBSCRIPTION_ID=<subscription-id>` | Target subscription |
| `AZURE_ENV_NAME=dev` | azd environment |
| `AZURE_LOCATION=<azure-region>` | Target region |
| `AZURE_RESOURCE_GROUP=rg-intake-dev` | Fixed target resource group |
| `AZURE_PRINCIPAL_ID=<service-principal-object-id>` | Deployer object ID |
| `GITHUB_REPOSITORY_OWNER=<owner>` | Repository owner |
| `GITHUB_REPOSITORY_NAME=<repository>` | Repository name |
| `GITHUB_RUNNER_PAT=<fine-grained-pat>` | Direct ACA secret input |
| `RUNNER_SHA256=<reviewed-sha256>` | Optional override; the pinned runner release digest is the default |

The PAT must be fine-grained, restricted to this repository, and have only the
repository administration access required to manage self-hosted runners.
Follow the organization's current GitHub permission policy if GitHub renames or
splits that permission.

### 4. Run the foundation/bootstrap

From the repository root, run:

```bash
bash scripts/azure/bootstrap-runner.sh
```

The script performs the following ordered operations:

1. Runs `azd provision` for the application foundation. This uses
   resource-group-scoped `infra/main.bicep` and creates no runner resources.
2. Invokes `infra/bootstrap-runner.bicep` with `deployRunnerJob=false`. This
   first bootstrap-template stage creates the runner identity, AAD-only
   private ACR, private endpoint, and the identity's `AcrPull` assignment.
3. Temporarily enables ACR public network access so Azure ACR Tasks can build
   and push the first runner image. ACR admin access remains disabled; the
   registry remains AAD-authenticated, not anonymous. An exit/signal trap
   restores public access to `Disabled`, including on build failure. Confirm
   `publicNetworkAccess` is `Disabled` before proceeding.
4. Invokes `infra/bootstrap-runner.bicep` again with
   `deployRunnerJob=true`. This second bootstrap-template stage creates the
   event-driven ACA Job with the immutable image reference and stores the PAT
   directly as its secure `github-pat` secret.

Thus `bootstrap-runner.bicep` has two stages; it is never called by
steady-state `azd provision`.

### 5. Validate external setup

Before declaring bootstrap complete:

- Confirm the ACR admin user is disabled and public network access is disabled.
- Confirm the runner identity has only `AcrPull` on the runner ACR.
- Confirm no idle runner replica or standing registered runner remains.
- Run `bash scripts/azure/runner/verify-pat-isolation.sh` and retain its proof
  that PID 1, child environments, and disk are clean before `run.sh`.
- Confirm the job-started hook admits the trusted deploy workflow and rejects
  PR, non-main, wrong-workflow, and wrong-repository contexts.
- Trigger the deploy workflow from the tip of `main`, approve the `dev`
  Environment, and confirm the `aca-intake-dev` runner takes exactly one job.
- Confirm OIDC login succeeds and the runner identity is not used for deploy.
- Confirm post-deploy verification runs after `azd deploy` and a verification
  failure makes the workflow fail.

Until all checks pass, external setup remains **pending**.

## Steady-state deployment

1. A PR targets protected `main`; credential-free CI runs on GitHub-hosted
   runners.
2. After merge, CI runs for the `main` push. Deploy is eligible only when its
   aggregate `Required Checks` job succeeds.
3. `.github/workflows/deploy.yml` receives the successful `workflow_run` event
   and waits for `dev` Environment approval.
4. The queued `aca-intake-dev` job causes ACA to start one ephemeral runner
   inside the VNet.
5. The workflow checks out the CI-verified SHA, installs setup-azd v2 and
   `microsoft.foundry`, logs in with GitHub OIDC, and fixes the azd resource
   group to `rg-intake-dev`.
6. A blocking Bicep what-if runs, then `azd provision` applies only
   `infra/main.bicep`.
7. `azd deploy` deploys application code, including the Foundry Hosted Agent.
8. `scripts/azure/post-deploy-verify.sh` runs **after deploy** as a blocking
   step. A failed check fails the deployment.
9. The ephemeral runner exits and deregisters; ACA returns to zero executions.

After ADR-015 implementation, the deployment gate must additionally pin and
deploy the MCP image, verify internal-only ingress and Foundry reachability,
verify Toolbox discovery and all four operations, reject invalid token cases,
prove contract-range overlap and idempotency, and verify Hosted Agent/MCP RBAC
separation. These are required future workflow capabilities, not a description
of the workflow currently present.

Manual `workflow_dispatch` must itself run from `main`. With no `ref` input it
deploys the current tip. For recovery, an optional full 40-character commit SHA
is accepted only when it is an ancestor of `origin/main` **and** GitHub reports
a successful push-triggered `CI` run for that exact SHA.

## PAT rotation

Rotate on the organization's fixed credential cadence and immediately after
suspected exposure:

1. Create a replacement fine-grained PAT with the same repository-only
   permission while keeping the old PAT valid.
2. Set the bootstrap shell inputs above, provide the replacement as
   `GITHUB_RUNNER_PAT`, and run:

   ```bash
   bash scripts/azure/bootstrap-runner.sh --skip-image-build
   ```

   This preserves the existing image and updates the direct ACA Job secret
   through the second bootstrap-template stage. No workflow, GitHub secret, or
   application code change is required.
3. Trigger and approve a deployment from the tip of `main`; confirm the labeled
   runner registers, completes one job, and deregisters.
4. Revoke the old PAT. If validation fails, restore a working direct ACA secret
   before revoking any known-good credential.

## Evidence and troubleshooting

The historical and contract evidence of record is
[`.azure/deployment-plan.md`](../../.azure/deployment-plan.md). Per-run evidence
is the Actions run log, uploaded what-if artifact, and `dev` Environment
deployment history.

| Symptom | Action |
|---|---|
| OIDC exchange fails | Match the Entra credential to the current environment-scoped subject; if immutable subjects were enabled, update Entra to the emitted immutable subject |
| No runner takes the job | Check label `aca-intake-dev`, ACA Job scaling, and the direct `github-pat` secret; rotate the PAT if expired |
| Private endpoint is unreachable | Confirm the step is on the ACA runner; never enable an application service's public access as a workaround |
| ACR remains public after bootstrap | Disable public access immediately and investigate the bootstrap trap/run log before any deploy |
| Runner remains registered | Manually deregister it, investigate cleanup, and do not proceed while a standing runner remains |
| Verification fails | Treat the deploy as failed; inspect verification output and runtime telemetry |
| Toolbox reports consent required | Confirm same-tenant Entra/Foundry setup and approved consent policy; complete the user flow, never use app-only fallback |
| Toolbox cannot reach/discover MCP | Check selected versions, readiness, private DNS/TLS, internal ingress, and Foundry private network; never enable public ingress |
| MCP token validation fails | Check signature, exact issuer/tenant, audience, lifetime, and delegated scope; do not weaken validation |
| MCP data access fails | Check the dedicated MCP UAMI and narrow Cosmos/Blob/Service Bus roles; do not forward the user token |

## Forward-only recovery

The preferred recovery is a new PR that reverts the faulty changes, preserving
the normal branch-protection and CI sequence. When a faster dev recovery is
needed, manually dispatch the workflow from `main` and provide the full SHA of a
known-good `main` commit. The workflow accepts it only after proving both main
ancestry and a successful push-triggered CI run, then still requires `dev`
Environment approval, OIDC, the ephemeral runner, and blocking verification.

This is forward-only for infrastructure: the selected source is reapplied
through the current deployment machinery. Do not use `azd down` or
resource-group teardown for routine recovery; `dev` contains persistent data.
Destructive reset remains a separate, explicitly human-confirmed operation
documented in the historical deployment plan.

For the requester boundary, roll back the Hosted Agent, Toolbox selection, MCP
image revision, and compatible contract as one reviewed release. There is no
automatic production fallback to embedded tools, the local API, or DevUI. If
the private path cannot be restored, stop requester mutations. See
[the MCP rollback procedure](requester-mcp.md#rollback).

## Out of scope

- `test` and `prod` environments, credentials, and triggers.
- A standing self-hosted runner.
- Azure deployment through the runner managed identity.
- Azure credentials or the runner PAT stored in GitHub Actions secrets.
- Automated destructive rollback.
