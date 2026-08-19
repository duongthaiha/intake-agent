#!/usr/bin/env bash
# Stage 1 of 2 — bootstrap stage. THIS is the only process that ever sees the
# GitHub PAT, and it never survives into the stage that runs workflow steps.
#
# Why two stages
# --------------
# `unset GITHUB_PAT` is NOT sufficient isolation. A process's initial
# environment block stays readable through /proc/<pid>/environ for the whole
# lifetime of that process, no matter what the shell later unsets: `unset`
# only edits the shell's own variable table. Workflow steps run as the same
# UID as PID 1, so a malicious (or merely approved-by-mistake) job could read
# /proc/1/environ and recover an administration-write PAT.
#
# So the PAT is confined to this stage, and PID 1 then `execve()`s the job
# stage with a freshly built, allow-listed environment (`env -i`). execve
# replaces the process image *including* the environment block, so from that
# point on /proc/1/environ physically no longer contains the PAT — there is
# nothing left to read. Verified end to end by
# scripts/azure/runner/verify-pat-isolation.sh.
#
# The short-lived registration token is handed across the exec boundary
# through a 0600 file on tmpfs (/dev/shm), never through the environment. The
# job stage reads it, deletes it, and only then configures the runner — so by
# the time ./run.sh can accept a job, neither the PAT nor the registration
# token exists in any environment block or on any filesystem.
#
# No removal token is minted. `--ephemeral` makes GitHub deregister the runner
# after exactly one job; holding a removal token for the duration of the job
# would reintroduce exactly the leak this design removes.

set -euo pipefail

: "${GITHUB_OWNER:?GITHUB_OWNER is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${RUNNER_LABELS:?RUNNER_LABELS is required}"
: "${GITHUB_PAT:?GITHUB_PAT is required}"
# Fail closed: the trusted-workflow job-started hook is mandatory defence in
# depth, so a job must never start on an image/deployment where it is absent.
: "${ACTIONS_RUNNER_HOOK_JOB_STARTED:?ACTIONS_RUNNER_HOOK_JOB_STARTED is required (trusted-workflow hook)}"

# INTAKE_* overrides exist so the isolation flow is testable outside a
# container; nothing in the deployed job sets them.
RUNNER_DIR="${INTAKE_RUNNER_DIR:-/home/runner/actions-runner}"
JOB_STAGE="${INTAKE_RUNNER_JOB_STAGE:-/opt/runner-bin/job-stage.sh}"

GITHUB_API_URL="${GITHUB_API_URL:-https://api.github.com}"
GITHUB_URL="${GITHUB_URL:-https://github.com}"
REPO_FULL="${GITHUB_OWNER}/${GITHUB_REPOSITORY}"

log() { echo "[entrypoint:bootstrap] $*"; }
fail() {
  echo "[entrypoint:bootstrap] ERROR: $*" >&2
  exit 1
}

# ---------------------------------------------------------------------------
# Validate the trusted-workflow hook before anything else
# ---------------------------------------------------------------------------
# The hook is what rejects a job that is not the deploy workflow on main. If it
# is missing, not executable, or writable by the runner user (i.e. tamperable
# by a workflow step), the container must refuse to register at all.
HOOK_PATH="$ACTIONS_RUNNER_HOOK_JOB_STARTED"
case "$HOOK_PATH" in
  /*) : ;;
  *) fail "ACTIONS_RUNNER_HOOK_JOB_STARTED must be an absolute path" ;;
esac
[[ -f "$HOOK_PATH" ]] || fail "job-started hook ${HOOK_PATH} does not exist"
[[ -x "$HOOK_PATH" ]] || fail "job-started hook ${HOOK_PATH} is not executable"
[[ ! -w "$HOOK_PATH" ]] || fail "job-started hook ${HOOK_PATH} is writable by the runner user"
HOOK_DIR="$(cd "$(dirname "$HOOK_PATH")" && pwd)"
[[ ! -w "$HOOK_DIR" ]] || fail "job-started hook directory ${HOOK_DIR} is writable by the runner user"
# GitHub's guidance: hooks must live outside the runner application directory,
# which a job can write to (_work, _diag, .credentials all live there).
case "$HOOK_PATH" in
  "${RUNNER_DIR}"/*) fail "the job-started hook must not live inside ${RUNNER_DIR}" ;;
esac
[[ -x "$JOB_STAGE" ]] || fail "job stage ${JOB_STAGE} is missing or not executable"

# ---------------------------------------------------------------------------
# Registration token → tmpfs file (never an environment variable)
# ---------------------------------------------------------------------------
# tmpfs is preferred so the token is never written to a backing device. The
# $HOME fallback keeps the runner usable on a host without /dev/shm; either
# way the file is 0600 and is deleted by the job stage before ./run.sh starts.
select_token_root() {
  local candidate
  for candidate in "${INTAKE_RUNNER_TOKEN_DIR:-}" /dev/shm "${XDG_RUNTIME_DIR:-}"; do
    if [[ -n "$candidate" && -d "$candidate" && -w "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  local fallback="${HOME:-/home/runner}/.runner-bootstrap"
  mkdir -p "$fallback" && chmod 700 "$fallback" || return 1
  echo "[entrypoint:bootstrap] WARNING: no tmpfs available; using ${fallback}" >&2
  printf '%s\n' "$fallback"
}

umask 077
TOKEN_ROOT="$(select_token_root)" || fail "no writable directory for the registration token"
TOKEN_DIR="$(mktemp -d "${TOKEN_ROOT}/runner-bootstrap.XXXXXX")" ||
  fail "could not create a private directory for the registration token"
TOKEN_FILE="${TOKEN_DIR}/registration-token"

# On any failure before the exec, remove the token material. After a successful
# exec this shell no longer exists and the job stage owns the deletion.
cleanup_token() { rm -rf "$TOKEN_DIR"; }
trap cleanup_token EXIT INT TERM

log "Requesting a registration token for ${REPO_FULL}"
# The response is piped straight to disk: the token is deliberately never
# assigned to a shell variable in this stage, so it cannot be exported by
# accident into the environment that is about to be replaced anyway.
if ! curl --fail --silent --show-error -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer ${GITHUB_PAT}" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "${GITHUB_API_URL}/repos/${REPO_FULL}/actions/runners/registration-token" |
  jq -er '.token' >"$TOKEN_FILE"; then
  fail "could not obtain a runner registration token; check the PAT's repository Actions/Administration/Metadata permissions"
fi
[[ -s "$TOKEN_FILE" ]] || fail "the registration token response was empty"
chmod 600 "$TOKEN_FILE"

# ---------------------------------------------------------------------------
# Hand over to the job stage with a clean environment
# ---------------------------------------------------------------------------
# Allow-list, not deny-list. Everything not named here is dropped by `env -i`,
# which includes GITHUB_PAT and — just as important — the Container Apps
# managed-identity endpoints (IDENTITY_ENDPOINT / IDENTITY_HEADER /
# MSI_ENDPOINT / MSI_SECRET). Workflow steps therefore cannot mint tokens for
# the runner's own user-assigned identity; GitHub OIDC stays the only Azure
# credential available inside a job.
clean_env=(
  "PATH=${PATH}"
  "HOME=${HOME:-/home/runner}"
  "USER=${USER:-runner}"
  "LOGNAME=${LOGNAME:-runner}"
  "LANG=${LANG:-C.UTF-8}"
  "ACTIONS_RUNNER_HOOK_JOB_STARTED=${HOOK_PATH}"
  "INTAKE_TRUSTED_REPOSITORY=${REPO_FULL}"
  "INTAKE_RUNNER_DIR=${RUNNER_DIR}"
  "INTAKE_RUNNER_TOKEN_FILE=${TOKEN_FILE}"
  "INTAKE_RUNNER_URL=${GITHUB_URL}/${REPO_FULL}"
  "INTAKE_RUNNER_LABELS=${RUNNER_LABELS}"
)
# Optional, non-secret pass-throughs. INTAKE_RUNNER_TOKEN_FILE is a path, not a
# secret — the file it names is deleted before any workflow step can run.
for optional in TZ INTAKE_ENVIRONMENT INTAKE_TRUSTED_WORKFLOW_PATH \
  INTAKE_TRUSTED_REF INTAKE_TRUSTED_EVENTS \
  http_proxy https_proxy no_proxy HTTP_PROXY HTTPS_PROXY NO_PROXY; do
  if [[ -n "${!optional:-}" ]]; then
    clean_env+=("${optional}=${!optional}")
  fi
done

log "Replacing PID $$ with the job stage — the PAT does not cross this boundary"
trap - EXIT INT TERM
exec /usr/bin/env -i "${clean_env[@]}" "$JOB_STAGE"
