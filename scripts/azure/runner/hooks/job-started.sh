#!/usr/bin/env bash
# ACTIONS_RUNNER_HOOK_JOB_STARTED — trusted-workflow admission control.
#
# The runner executes this file (as `bash -e <path>`) after a job has been
# assigned but *before* the first workflow step runs. A non-zero exit fails the
# job without running any step; `continue-on-error` cannot suppress it.
# See https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/run-scripts
#
# This is defence in depth, not the primary control. The primary controls are
# deploy.yml's triggers plus the `dev` Environment approval. This hook exists
# because the runner is VNet-connected and holds an OIDC path into Azure: if a
# job ever reaches it that is not the deploy workflow on main, the correct
# outcome is a failed job, not a deployment.
#
# Why the expected values cannot be forged by the job:
#   * GITHUB_REPOSITORY / GITHUB_WORKFLOW_REF / GITHUB_REF / GITHUB_EVENT_NAME
#     are injected by the runner from the server-side `github` context. The
#     runner passes hooks an empty step-environment dictionary, so workflow
#     `env:` blocks never reach this script.
#   * INTAKE_TRUSTED_* come from the runner process environment, built by
#     entrypoint.sh from the Container Apps job definition before the runner
#     was ever configured.
#   * The file itself is root-owned and read-only inside the image, and
#     entrypoint.sh refuses to start if it is writable by the runner user.

set -euo pipefail

# Baked, deliberately strict defaults. Only the repository is supplied at
# runtime (from the ARM template, via entrypoint.sh).
EXPECTED_REPOSITORY="${INTAKE_TRUSTED_REPOSITORY:-}"
EXPECTED_WORKFLOW_PATH="${INTAKE_TRUSTED_WORKFLOW_PATH:-.github/workflows/deploy.yml}"
EXPECTED_REF="${INTAKE_TRUSTED_REF:-refs/heads/main}"
ALLOWED_EVENTS="${INTAKE_TRUSTED_EVENTS:-workflow_run workflow_dispatch}"

deny() {
  # ::error:: surfaces in the "Set up runner" step of the failed job.
  echo "::error::Untrusted job rejected by the self-hosted runner admission hook: $1"
  echo "[job-started-hook] DENIED: $1" >&2
  exit 1
}

if [[ -z "$EXPECTED_REPOSITORY" ]]; then
  deny "the runner was started without INTAKE_TRUSTED_REPOSITORY, so no job can be trusted"
fi

ACTUAL_REPOSITORY="${GITHUB_REPOSITORY:-}"
ACTUAL_WORKFLOW_REF="${GITHUB_WORKFLOW_REF:-}"
ACTUAL_REF="${GITHUB_REF:-}"
ACTUAL_EVENT="${GITHUB_EVENT_NAME:-}"

EXPECTED_WORKFLOW_REF="${EXPECTED_REPOSITORY}/${EXPECTED_WORKFLOW_PATH}@${EXPECTED_REF}"

if [[ "$ACTUAL_REPOSITORY" != "$EXPECTED_REPOSITORY" ]]; then
  deny "repository '${ACTUAL_REPOSITORY:-<unset>}' is not '${EXPECTED_REPOSITORY}'"
fi

# Pinning the full workflow ref covers both halves of the trust boundary: the
# workflow definition (.github/workflows/deploy.yml) and the ref it was loaded
# from (refs/heads/main, a protected branch). A reusable workflow called from
# somewhere else, a renamed copy, or the same file on another branch all fail.
if [[ "$ACTUAL_WORKFLOW_REF" != "$EXPECTED_WORKFLOW_REF" ]]; then
  deny "workflow ref '${ACTUAL_WORKFLOW_REF:-<unset>}' is not '${EXPECTED_WORKFLOW_REF}'"
fi

if [[ "$ACTUAL_REF" != "$EXPECTED_REF" ]]; then
  deny "ref '${ACTUAL_REF:-<unset>}' is not '${EXPECTED_REF}'"
fi

event_allowed=false
for allowed in $ALLOWED_EVENTS; do
  if [[ "$ACTUAL_EVENT" == "$allowed" ]]; then
    event_allowed=true
    break
  fi
done
if [[ "$event_allowed" != "true" ]]; then
  deny "event '${ACTUAL_EVENT:-<unset>}' is not one of: ${ALLOWED_EVENTS}"
fi

echo "[job-started-hook] ALLOWED: ${ACTUAL_EVENT} ${ACTUAL_WORKFLOW_REF}"
exit 0
