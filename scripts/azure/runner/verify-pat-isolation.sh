#!/usr/bin/env bash
# Container-level reproduction of the runner PAT-isolation property.
#
# Substring assertions in tests/unit/test_deployment_cicd_static.py prove the
# *shape* of entrypoint.sh. This script proves the *behaviour*, at the only
# layer where it actually matters: a real Linux container, with a real PID 1,
# reading /proc/1/environ the way a malicious workflow step would.
#
# It runs three checks in one container:
#   1. POSITIVE CONTROL — during the bootstrap stage, a sentinel PAT *is*
#      readable from /proc/1/environ. Without this, "no PAT found" later would
#      be meaningless (a broken detector always passes).
#   2. ISOLATION — after entrypoint.sh execs the job stage, neither the
#      sentinel PAT nor the sentinel registration token appears in
#      /proc/1/environ, in any process environment, or anywhere on disk, at
#      the moment config.sh runs and at the moment run.sh starts.
#   3. ADMISSION — the baked-in ACTIONS_RUNNER_HOOK_JOB_STARTED hook is wired,
#      non-writable by the runner user, and rejects untrusted jobs while
#      admitting the trusted deploy workflow on main.
#
# The real entrypoint.sh, job-stage.sh and hooks/job-started.sh are used
# verbatim, at the same paths and permissions the production Dockerfile
# installs them to. Only what the property does not depend on is stubbed:
# `curl` (GitHub's API) and the runner's own config.sh / run.sh. The
# verification image deliberately omits the Azure CLI and the runner tarball —
# neither participates in credential isolation, and leaving them out keeps
# this reproduction fast and offline-friendly.
#
# Usage:
#   bash scripts/azure/runner/verify-pat-isolation.sh
#
# Requires a working Docker daemon (exit code 2 if unavailable). Exits
# non-zero on any failed assertion.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_TAG="intake-runner-pat-isolation-verify:local"
CONTEXT_DIR="${SCRIPT_DIR}/.verify-context.$$"
SENTINEL_PAT="ghp_SENTINELPATVALUEDONOTUSE0000000000"
SENTINEL_REG_TOKEN="SENTINELREGISTRATIONTOKEN0000000000"
OWNER="intake-owner"
REPO="intake-agent"

command -v docker >/dev/null || {
  echo "docker is required for this verification" >&2
  exit 2
}
docker info >/dev/null 2>&1 || {
  echo "the Docker daemon is not reachable" >&2
  exit 2
}

cleanup() { rm -rf "$CONTEXT_DIR"; }
trap cleanup EXIT INT TERM

mkdir -p "$CONTEXT_DIR/hooks" "$CONTEXT_DIR/stubs"
cp "$SCRIPT_DIR/entrypoint.sh" "$SCRIPT_DIR/job-stage.sh" "$CONTEXT_DIR/"
cp "$SCRIPT_DIR/hooks/job-started.sh" "$CONTEXT_DIR/hooks/"

# --- stub curl: GitHub's registration-token API, plus the positive control ---
cat >"$CONTEXT_DIR/stubs/curl" <<STUB
#!/usr/bin/env bash
set -euo pipefail
if [[ "\${GITHUB_PAT:-}" != "${SENTINEL_PAT}" ]]; then
  echo "STUB-CURL: the bootstrap stage did not hold the sentinel PAT" >&2
  exit 1
fi
if ! tr '\0' '\n' </proc/1/environ | grep -q "^GITHUB_PAT=${SENTINEL_PAT}\$"; then
  echo "STUB-CURL: expected the sentinel PAT in /proc/1/environ during bootstrap" >&2
  exit 1
fi
echo "CHECK-1-POSITIVE-CONTROL-PID1-EXPOSES-PAT" >&2
printf '{"token":"%s"}\n' "${SENTINEL_REG_TOKEN}"
STUB

# --- stub config.sh: runs as a child of the clean PID 1 ---
cat >"$CONTEXT_DIR/stubs/config.sh" <<STUB
#!/usr/bin/env bash
set -uo pipefail
fail() { echo "CONFIG-STUB FAIL: \$*" >&2; exit 1; }

token=""
while [[ \$# -gt 0 ]]; do
  case "\$1" in
    --token) token="\$2"; shift 2 ;;
    *) shift ;;
  esac
done
[[ "\$token" == "${SENTINEL_REG_TOKEN}" ]] || fail "config.sh did not receive the registration token"
echo "CHECK-2-CONFIG-RECEIVED-REGISTRATION-TOKEN" >&2

pid1_env="\$(tr '\0' '\n' </proc/1/environ)"
if grep -q "${SENTINEL_PAT}" <<<"\$pid1_env"; then fail "the PAT is still in /proc/1/environ"; fi
echo "CHECK-3-PID1-HAS-NO-PAT" >&2
if grep -q "${SENTINEL_REG_TOKEN}" <<<"\$pid1_env"; then fail "the registration token is in /proc/1/environ"; fi
echo "CHECK-4-PID1-HAS-NO-REGISTRATION-TOKEN" >&2

if grep -q "${SENTINEL_PAT}" /proc/self/environ; then fail "the PAT was inherited by config.sh"; fi
if grep -q "${SENTINEL_REG_TOKEN}" /proc/self/environ; then fail "the token was exported to config.sh"; fi
echo "CHECK-5-CONFIG-ENV-HAS-NEITHER-SECRET" >&2

if [[ -e "\${INTAKE_RUNNER_TOKEN_FILE}" ]]; then fail "the registration token file still exists"; fi
echo "CHECK-6-TOKEN-FILE-DELETED-BEFORE-CONFIG" >&2
exit 0
STUB

# --- stub run.sh: this is the process that would accept an untrusted job ---
# --exclude below skips this file and config.sh: the stubs necessarily embed
# the sentinels to assert on them. Nothing else on the scanned paths may.
cat >"$CONTEXT_DIR/stubs/run.sh" <<STUB
#!/usr/bin/env bash
set -uo pipefail
fail() { echo "RUN-STUB FAIL: \$*" >&2; exit 1; }

pid1_env="\$(tr '\0' '\n' </proc/1/environ)"
if grep -q "${SENTINEL_PAT}" <<<"\$pid1_env"; then fail "the PAT is in /proc/1/environ at run.sh time"; fi
if grep -q "${SENTINEL_REG_TOKEN}" <<<"\$pid1_env"; then fail "the token is in /proc/1/environ at run.sh time"; fi
echo "CHECK-7-PID1-CLEAN-WHEN-RUN-SH-STARTS" >&2

if grep -rq --exclude=config.sh --exclude=run.sh \
     -e "${SENTINEL_PAT}" -e "${SENTINEL_REG_TOKEN}" \
     /dev/shm /home/runner /opt 2>/dev/null; then
  fail "a sentinel credential is readable somewhere on disk"
fi
echo "CHECK-8-NO-SENTINEL-ON-DISK" >&2

hook="\${ACTIONS_RUNNER_HOOK_JOB_STARTED:?the hook is not configured}"
[[ -x "\$hook" ]] || fail "the hook is not executable"
[[ ! -w "\$hook" ]] || fail "the hook is writable by the runner user"
case "\$hook" in /home/runner/actions-runner/*) fail "the hook lives in the runner application directory" ;; esac
echo "CHECK-9-HOOK-WIRED-AND-IMMUTABLE" >&2

trusted_env=(
  "GITHUB_REPOSITORY=${OWNER}/${REPO}"
  "GITHUB_WORKFLOW_REF=${OWNER}/${REPO}/.github/workflows/deploy.yml@refs/heads/main"
  "GITHUB_REF=refs/heads/main"
  "GITHUB_EVENT_NAME=workflow_run"
)
env "\${trusted_env[@]}" bash -e "\$hook" >/dev/null || fail "the hook rejected the trusted deploy workflow"
echo "CHECK-10-HOOK-ADMITS-TRUSTED-DEPLOY" >&2

untrusted=(
  "GITHUB_REF=refs/heads/attacker"
  "GITHUB_WORKFLOW_REF=${OWNER}/${REPO}/.github/workflows/attacker.yml@refs/heads/main"
  "GITHUB_WORKFLOW_REF=${OWNER}/${REPO}/.github/workflows/deploy.yml@refs/pull/1/merge"
  "GITHUB_EVENT_NAME=pull_request"
  "GITHUB_REPOSITORY=attacker/${REPO}"
)
for bad in "\${untrusted[@]}"; do
  if env "\${trusted_env[@]}" "\$bad" bash -e "\$hook" >/dev/null 2>&1; then
    fail "the hook admitted an untrusted job (\$bad)"
  fi
done
echo "CHECK-11-HOOK-REJECTS-UNTRUSTED-JOBS" >&2
exit 0
STUB

# --- verification image: production paths, production permissions ---
cat >"$CONTEXT_DIR/Dockerfile" <<'DOCKERFILE'
FROM ubuntu:22.04
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends jq ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -s /bin/bash runner \
    && mkdir -p /home/runner/actions-runner \
    && chown -R runner:runner /home/runner/actions-runner
COPY stubs/curl /usr/local/bin/curl
COPY stubs/config.sh stubs/run.sh /home/runner/actions-runner/
COPY entrypoint.sh job-stage.sh /opt/runner-bin/
COPY hooks/job-started.sh /opt/runner-hooks/
RUN chmod 0555 /usr/local/bin/curl /home/runner/actions-runner/config.sh \
      /home/runner/actions-runner/run.sh /opt/runner-bin/entrypoint.sh \
      /opt/runner-bin/job-stage.sh /opt/runner-hooks/job-started.sh \
    && chmod 0555 /opt/runner-bin /opt/runner-hooks
USER runner
WORKDIR /home/runner
ENTRYPOINT ["/opt/runner-bin/entrypoint.sh"]
DOCKERFILE

echo "━━━ Building the verification image ━━━"
docker build --quiet --tag "$IMAGE_TAG" "$CONTEXT_DIR" >/dev/null

echo "━━━ Running the isolation reproduction ━━━"
# IDENTITY_* are injected here on purpose: Container Apps supplies them to any
# job with a managed identity, and they must not survive the exec either.
set +e
output="$(docker run --rm \
  --env "GITHUB_PAT=${SENTINEL_PAT}" \
  --env "GITHUB_OWNER=${OWNER}" \
  --env "GITHUB_REPOSITORY=${REPO}" \
  --env "RUNNER_LABELS=aca-intake-dev" \
  --env "INTAKE_ENVIRONMENT=dev" \
  --env "ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/runner-hooks/job-started.sh" \
  --env "IDENTITY_ENDPOINT=http://169.254.169.254/metadata/identity/oauth2/token" \
  --env "IDENTITY_HEADER=sentinel-managed-identity-header" \
  "$IMAGE_TAG" 2>&1)"
status=$?
set -e
echo "$output"

if [[ $status -ne 0 ]]; then
  echo "❌ The container exited ${status}; PAT isolation is NOT proven." >&2
  exit 1
fi

expected_checks=(
  CHECK-1-POSITIVE-CONTROL-PID1-EXPOSES-PAT
  CHECK-2-CONFIG-RECEIVED-REGISTRATION-TOKEN
  CHECK-3-PID1-HAS-NO-PAT
  CHECK-4-PID1-HAS-NO-REGISTRATION-TOKEN
  CHECK-5-CONFIG-ENV-HAS-NEITHER-SECRET
  CHECK-6-TOKEN-FILE-DELETED-BEFORE-CONFIG
  CHECK-7-PID1-CLEAN-WHEN-RUN-SH-STARTS
  CHECK-8-NO-SENTINEL-ON-DISK
  CHECK-9-HOOK-WIRED-AND-IMMUTABLE
  CHECK-10-HOOK-ADMITS-TRUSTED-DEPLOY
  CHECK-11-HOOK-REJECTS-UNTRUSTED-JOBS
)
missing=0
for check in "${expected_checks[@]}"; do
  if ! grep -q "$check" <<<"$output"; then
    echo "❌ missing evidence: ${check}" >&2
    missing=1
  fi
done
[[ $missing -eq 0 ]] || exit 1

docker image rm --force "$IMAGE_TAG" >/dev/null 2>&1 || true

echo
echo "✅ PAT isolation verified in a real container:"
echo "   • the sentinel PAT is readable from /proc/1/environ during bootstrap (the detector works)"
echo "   • it is gone from /proc/1/environ, from every process environment and from disk"
echo "     before config.sh runs and before run.sh can accept a job"
echo "   • the trusted-workflow hook is wired, immutable, and enforcing"
