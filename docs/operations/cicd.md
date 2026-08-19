# CI/CD Operator Runbook — `dev` deployment pipeline

> **Current status (2026-08-19):** the workflow, Bicep, and runner bootstrap
> implementation exists in this branch. The GitHub `dev` Environment now has a
> required reviewer and a `main`-only deployment policy, but branch protection,
> Azure-backed variables/OIDC roles, and the runner bootstrap are still pending.
> Until an operator completes and validates those items, the deploy workflow is
> not operational. `test` and `prod` remain unconfigured and out of scope.

## Architecture and trust boundaries

The steady-state template, [`infra/main.bicep`](../../infra/main.bicep), is
resource-group scoped. It deploys application infrastructure into the existing
`rg-intake-dev` resource group and deliberately excludes all runner resources.
Runner infrastructure is created or updated only through
[`scripts/azure/bootstrap-runner.sh`](../../scripts/azure/bootstrap-runner.sh),
which invokes
[`infra/bootstrap-runner.bicep`](../../infra/bootstrap-runner.bicep) out of
band.

Private-network provisioning, Functions deployment, both Foundry agent
definitions, the private MCP service, and live verification run on a
repository-scoped, ephemeral Azure
Container Apps Jobs runner labeled `aca-intake-dev`. The runner registers with
`--ephemeral`, accepts one labeled job, and is removed after it finishes. The
job scales to zero between runs.

The two identities have separate responsibilities:

| Identity | Authentication | Permissions |
|---|---|---|
| Azure deployer | GitHub OIDC workload identity federation | Resource-group-scoped deployment/RBAC permissions |
| Runner user-assigned managed identity | Azure managed identity | `AcrPull` on the runner ACR only |
| Prompt MCP user-assigned managed identity | Azure managed identity | Cosmos database, artifacts container, and private ACR access only |
| Prompt end user | Delegated Entra token | Requester operations for that verified tenant/user only |

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
| `INTAKE_MCP_APP_CLIENT_ID` | Client ID output by `bootstrap-prompt-intake-auth.*`; not a secret |

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

### 3. Bootstrap delegated prompt-agent authentication

Run `scripts/azure/bootstrap-prompt-intake-auth.sh` or its PowerShell
counterpart once. The script creates or reuses a single-tenant Entra API
application, exposes `access_as_user`, creates no client secret, and prints the
client ID/audience. Store only the client ID as `INTAKE_MCP_APP_CLIENT_ID`.

Each same-tenant user consents on first tool use. CI cannot complete this
interactive consent and must not substitute a shared workload identity.

### 4. Prepare bootstrap inputs

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
| `INTAKE_MCP_APP_CLIENT_ID=<application-client-id>` | Secretless delegated MCP API registration |

The PAT must be fine-grained, restricted to this repository, and have only the
repository administration access required to manage self-hosted runners.
Follow the organization's current GitHub permission policy if GitHub renames or
splits that permission.

### 5. Run the foundation/bootstrap

From the repository root, run:

```bash
bash scripts/azure/bootstrap-runner.sh
```

The script performs the following ordered operations:

1. Seeds the azd environment and creates the runner identity plus AAD-only ACR
   without the private endpoint, allowing the first controlled build.
2. Builds both immutable runner and prompt-MCP images. ACR admin access remains
   disabled and an exit/signal trap always restores public access to disabled.
3. Sets the MCP client ID/image in azd and runs resource-group-scoped
   `infra/main.bicep`, which creates the application network and private MCP
   runtime but no runner resources.
4. Reapplies `infra/bootstrap-runner.bicep` with the ACR private endpoint,
   public access disabled, and `deployRunnerJob=true`.

Thus `bootstrap-runner.bicep` has two stages; it is never called by
steady-state `azd provision`.

### 6. Validate external setup

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
- Complete the manual two-user prompt acceptance: each user consents, each sees
  only their own requests, and cross-user/cross-tenant request IDs return not
  found.

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
6. The workflow temporarily opens the AAD-only ACR data-plane path, builds a
   commit-SHA-tagged MCP image through ACR Tasks, resolves its immutable digest,
   and restores public access to disabled under an exit/signal trap. It then
   sets the digest plus Entra client ID in azd.
7. A blocking Bicep what-if runs, then `azd provision` applies only
   `infra/main.bicep`.
8. `azd deploy` deploys application code, including the Foundry Hosted Agent.
9. The workflow upserts the `user-entra-token` MCP connection and creates or
   reuses the immutable `prompt-intake-agent` version.
10. `scripts/azure/post-deploy-verify.sh` runs **after deploy** as a blocking
   step. A failed check fails the deployment.
11. The ephemeral runner exits and deregisters; ACA returns to zero executions.

Manual `workflow_dispatch` must itself run from `main`. With no `ref` input it
deploys the current tip. For recovery, an optional full 40-character commit SHA
is accepted only when it is an ancestor of `origin/main` **and** GitHub reports
a successful push-triggered `CI` run for that exact SHA. Recovery commits must
also contain the prompt-agent deployment contract; commits from before this
side-by-side migration are rejected before Azure login.

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
| Prompt MCP returns 401 after consent | Confirm the audience is `api://<INTAKE_MCP_APP_CLIENT_ID>`, scope is `access_as_user`, and the token tenant matches the Foundry tenant |
| Prompt MCP is unreachable | Confirm the internal Container Apps default-domain private DNS wildcard resolves from the Foundry delegated subnet |
| Prompt agent lists no Hosted Agent requests | Expected: the surfaces use separate verified identity namespaces and do not automatically link requests |
| ACR remains public after bootstrap | Disable public access immediately and investigate the bootstrap trap/run log before any deploy |
| Runner remains registered | Manually deregister it, investigate cleanup, and do not proceed while a standing runner remains |
| Verification fails | Treat the deploy as failed; inspect verification output and runtime telemetry |

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

The prompt path can be rolled back independently by restoring a prior MCP image
and prompt-agent version or deleting its project connection. Do not remove the
shared request-ownership checks; they are a defense-in-depth security fix for
both surfaces.

## Out of scope

- `test` and `prod` environments, credentials, and triggers.
- A standing self-hosted runner.
- Azure deployment through the runner managed identity.
- Azure credentials or the runner PAT stored in GitHub Actions secrets.
- Automated destructive rollback.
