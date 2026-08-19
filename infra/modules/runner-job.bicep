// Runner job — ephemeral, event-driven GitHub Actions Container Apps Job.
// Deployed into the *existing* cae-intake-<env> Managed Environment (passed
// in via environmentId) so it shares that environment's VNet integration,
// Log Analytics wiring and Consumption workload profile — no second
// environment or subnet is created.
//
// Security model:
//   - triggerType=Event, KEDA `github-runner` scale rule polls GitHub (pull
//     model); minExecutions=0 (no idle replicas), maxExecutions=1 (never
//     more than one concurrent runner).
//   - The container entrypoint runs in two stages: a bootstrap stage that
//     holds the PAT only long enough to mint a registration token, then an
//     `exec` into a clean, allow-listed environment (so /proc/1/environ no
//     longer contains the PAT — or this job's managed-identity endpoints —
//     by the time run.sh can accept a job). It registers repo-scoped +
//     `--ephemeral` (GitHub deregisters it automatically after exactly one
//     job, so no removal token is retained) and exits.
//   - ACTIONS_RUNNER_HOOK_JOB_STARTED below points at a baked-in, root-owned
//     admission hook that fails any assigned job that is not the deploy
//     workflow on main. Defence in depth behind deploy.yml's triggers and the
//     `dev` Environment approval.
//   - The job's own managed identity (runnerIdentityId) is used ONLY to
//     pull the image from ACR. It is
//     granted no Azure deployment RBAC (no Contributor / UAA / Foundry
//     Owner) — GitHub OIDC inside the running job is the sole Azure
//     deployment identity (see .github/workflows/deploy.yml).
//   - The GitHub PAT value is never present in this template: `secrets`
//     receives it through a secure bootstrap deployment parameter. The runner
//     identity has no access to the application's Key Vault.
targetScope = 'resourceGroup'

param location string
param tags object
param jobName string
param environmentId string
param workloadProfileName string = 'Consumption'
param runnerIdentityId string
param acrLoginServer string
@secure()
@description('Fine-grained, repository-scoped GitHub PAT. It is stored only as this job secret.')
param githubPat string
@minLength(1)
@description('Immutable runner image reference created by the bootstrap build stage.')
param runnerImage string
@minLength(1)
@description('GitHub repository owner (org or user) that owns the runner registration. Required — the scale rule and registration token calls are meaningless without it.')
param githubRepoOwner string
@minLength(1)
@description('GitHub repository name (no owner prefix) the runner registers against.')
param githubRepoName string
@description('Self-hosted runner label. Must never be referenced by any pull_request-triggered workflow (public repo — fork PRs must never reach this private runner).')
param runnerLabel string = 'aca-intake-dev'
param environmentNameTag string

@description('Absolute path of the baked-in job-started admission hook. Must match the path scripts/azure/runner/Dockerfile installs root-owned and read-only; the entrypoint refuses to register a runner if it is missing or writable.')
param jobStartedHookPath string = '/opt/runner-hooks/job-started.sh'

resource runnerJob 'Microsoft.App/jobs@2024-03-01' = {
  name: jobName
  location: location
  tags: union(tags, { 'azd-service-name': 'github-runner' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${runnerIdentityId}': {}
    }
  }
  properties: {
    environmentId: environmentId
    workloadProfileName: workloadProfileName
    configuration: {
      triggerType: 'Event'
      replicaTimeout: 3600 // 1 hour ceiling per execution — matches ephemeral runner registration TTL
      replicaRetryLimit: 0 // never retry a failed/expired ephemeral registration automatically
      registries: [
        {
          server: acrLoginServer
          identity: runnerIdentityId
        }
      ]
      secrets: [
        {
          name: 'github-pat'
          value: githubPat
        }
      ]
      eventTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
        scale: {
          minExecutions: 0
          maxExecutions: 1
          pollingInterval: 30
          rules: [
            {
              name: 'github-runner'
              type: 'github-runner'
              metadata: {
                githubApiURL: 'https://api.github.com'
                owner: githubRepoOwner
                runnerScope: 'repo'
                repos: githubRepoName
                labels: runnerLabel
                targetWorkflowQueueLength: '1'
              }
              auth: [
                {
                  secretRef: 'github-pat'
                  triggerParameter: 'personalAccessToken'
                }
              ]
            }
          ]
        }
      }
    }
    template: {
      containers: [
        {
          name: 'github-runner'
          image: runnerImage
          resources: {
            cpu: json('2.0')
            memory: '4.0Gi'
          }
          env: [
            {
              name: 'GITHUB_OWNER'
              value: githubRepoOwner
            }
            {
              name: 'GITHUB_REPOSITORY'
              value: githubRepoName
            }
            {
              name: 'RUNNER_LABELS'
              value: runnerLabel
            }
            {
              name: 'GITHUB_PAT'
              secretRef: 'github-pat'
            }
            {
              name: 'INTAKE_ENVIRONMENT'
              value: environmentNameTag
            }
            // Trusted-workflow admission control. The GitHub runner executes
            // this script after a job is assigned but before its first step;
            // a non-zero exit fails the job and no step ever runs, and
            // `continue-on-error` cannot suppress it. The hook rejects
            // anything that is not .github/workflows/deploy.yml@refs/heads/main
            // for this repository, triggered by workflow_run/workflow_dispatch.
            {
              name: 'ACTIONS_RUNNER_HOOK_JOB_STARTED'
              value: jobStartedHookPath
            }
          ]
        }
      ]
      initContainers: []
    }
  }
}

output jobId string = runnerJob.id
output jobName string = runnerJob.name
