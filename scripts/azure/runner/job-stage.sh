#!/usr/bin/env bash
# Stage 2 of 2 — job stage. Reached only via `exec` from entrypoint.sh, so this
# process (PID 1 in the container) was created with a clean, allow-listed
# environment block: /proc/1/environ contains no PAT, no registration token and
# no Container Apps managed-identity credentials.
#
# Responsibilities, in order:
#   1. assert the exec boundary actually held (fail closed if it did not),
#   2. read the registration token from its tmpfs file and delete the file,
#   3. configure the ephemeral runner with the token as a non-exported shell
#      variable, then unset it,
#   4. exec ./run.sh, which accepts exactly one job.
#
# By step 4 there is no secret left anywhere a workflow step can reach: not in
# this process's environment, not in a child's, not on disk.

set -euo pipefail

: "${INTAKE_RUNNER_TOKEN_FILE:?INTAKE_RUNNER_TOKEN_FILE is required}"
: "${INTAKE_RUNNER_URL:?INTAKE_RUNNER_URL is required}"
: "${INTAKE_RUNNER_LABELS:?INTAKE_RUNNER_LABELS is required}"
: "${ACTIONS_RUNNER_HOOK_JOB_STARTED:?ACTIONS_RUNNER_HOOK_JOB_STARTED is required (trusted-workflow hook)}"

RUNNER_DIR="${INTAKE_RUNNER_DIR:-/home/runner/actions-runner}"

log() { echo "[entrypoint:job-stage] $*"; }
fail() {
  echo "[entrypoint:job-stage] ERROR: $*" >&2
  exit 1
}

# ---------------------------------------------------------------------------
# 1. Prove the clean-exec boundary held
# ---------------------------------------------------------------------------
# A regression in entrypoint.sh (a forgotten allow-list entry, a plain `exec`
# instead of `env -i`) must stop the container, not silently hand a live
# credential to an untrusted workflow job.
for forbidden in GITHUB_PAT GITHUB_TOKEN IDENTITY_HEADER IDENTITY_ENDPOINT \
  MSI_SECRET MSI_ENDPOINT AZURE_CLIENT_ID; do
  if [[ -n "${!forbidden:-}" ]]; then
    fail "${forbidden} survived the clean-environment exec — refusing to register a runner"
  fi
done

# Direct evidence rather than inference, where /proc is available: the kernel's
# copy of PID 1's environment block is what an attacking job would read.
if [[ -r /proc/1/environ ]]; then
  if tr '\0' '\n' </proc/1/environ | grep -Eq '^(GITHUB_PAT|IDENTITY_HEADER|MSI_SECRET)='; then
    fail "/proc/1/environ still exposes runner bootstrap credentials — refusing to register a runner"
  fi
  log "/proc/1/environ verified free of bootstrap credentials"
fi

# ---------------------------------------------------------------------------
# 2. Consume and destroy the registration token file
# ---------------------------------------------------------------------------
[[ -f "$INTAKE_RUNNER_TOKEN_FILE" ]] || fail "registration token file is missing"
# Non-exported on purpose: it must never appear in this process's environment
# block, nor be inherited by anything except the config.sh child below.
REG_TOKEN="$(cat "$INTAKE_RUNNER_TOKEN_FILE")"
TOKEN_DIR="$(dirname "$INTAKE_RUNNER_TOKEN_FILE")"
rm -f "$INTAKE_RUNNER_TOKEN_FILE"
rmdir "$TOKEN_DIR" 2>/dev/null || true
[[ ! -e "$INTAKE_RUNNER_TOKEN_FILE" ]] ||
  fail "could not delete ${INTAKE_RUNNER_TOKEN_FILE} — refusing to start a job with a readable token on disk"
[[ -n "$REG_TOKEN" ]] || fail "the registration token file was empty"
log "Registration token consumed; ${INTAKE_RUNNER_TOKEN_FILE} deleted"

# ---------------------------------------------------------------------------
# 3. Configure the ephemeral runner
# ---------------------------------------------------------------------------
cd "$RUNNER_DIR"
RUNNER_INSTANCE_NAME="aca-${INTAKE_ENVIRONMENT:-dev}-$(date +%s)-${HOSTNAME:-$$}"

log "Configuring ephemeral runner ${RUNNER_INSTANCE_NAME} with labels: ${INTAKE_RUNNER_LABELS}"
# config.sh only accepts the token as an argument. That is acceptable here and
# only here: the runner is not listening yet, so no untrusted job process
# exists to read /proc/<pid>/cmdline, and the process is gone before one can.
# The token is single-use and expires in an hour regardless.
./config.sh \
  --url "$INTAKE_RUNNER_URL" \
  --token "$REG_TOKEN" \
  --name "$RUNNER_INSTANCE_NAME" \
  --labels "$INTAKE_RUNNER_LABELS" \
  --unattended \
  --ephemeral \
  --replace

unset REG_TOKEN

# ---------------------------------------------------------------------------
# 4. Run exactly one job
# ---------------------------------------------------------------------------
# `--ephemeral` means GitHub deregisters this runner once the job finishes, so
# no removal token is retained anywhere. The job-started hook validated above
# runs before the first workflow step and fails the job unless it is the
# trusted deploy workflow on main.
log "Runner registered — handing PID $$ to run.sh (hook: ${ACTIONS_RUNNER_HOOK_JOB_STARTED})"
exec ./run.sh
