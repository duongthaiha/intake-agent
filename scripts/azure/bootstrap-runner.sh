#!/usr/bin/env bash
# Bootstrap the private runner outside azd provision. Stages are idempotent:
# foundation, image build/push, then ACA Job creation/secret rotation.
# A private ACR needs temporary public access or a dedicated private build pool
# for the first push. This script uses the former and restores it with a trap.
#
# Two modes:
#   (default)            full bootstrap — seeds the azd environment, provisions
#                        the application foundation, builds/pushes the runner
#                        image, then creates/updates the runner job.
#   --skip-image-build   PAT-only rotation — reuses the image already running
#                        on the job and re-deploys ONLY the bootstrap template.
#                        Deliberately does not run `azd provision`: rotating a
#                        secret must never reprovision the whole application
#                        foundation.
#
# Required environment variables:
#   AZURE_SUBSCRIPTION_ID     — target subscription (no implicit `az account` default)
#   AZURE_PRINCIPAL_ID        — federated service principal object ID
#   GITHUB_REPOSITORY_OWNER   — repo owner for the runner registration
#   GITHUB_REPOSITORY_NAME    — repo name for the runner registration
#   GITHUB_RUNNER_PAT         — fine-grained, repository-scoped PAT
# Optional:
#   AZURE_ENV_NAME (dev), AZURE_LOCATION (eastus2), AZURE_RESOURCE_GROUP
#   RUNNER_SHA256             — override the pinned actions-runner digest only
#                               when intentionally moving off the default
#                               (see scripts/azure/runner/Dockerfile).

set -euo pipefail

ENV_NAME="${AZURE_ENV_NAME:-dev}"
LOCATION="${AZURE_LOCATION:-eastus2}"
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-rg-intake-${ENV_NAME}}"
IMAGE_TAG="runner-$(git rev-parse --short=12 HEAD)"
SKIP_IMAGE_BUILD=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-image-build) SKIP_IMAGE_BUILD=true; shift ;;
    --image-tag) IMAGE_TAG="${2:?--image-tag requires a value}"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

command -v az >/dev/null || { echo "az CLI is required." >&2; exit 1; }
command -v azd >/dev/null || { echo "azd is required." >&2; exit 1; }
: "${AZURE_SUBSCRIPTION_ID:?AZURE_SUBSCRIPTION_ID must be the target subscription ID}"
: "${AZURE_PRINCIPAL_ID:?AZURE_PRINCIPAL_ID must be the federated service principal object ID}"
: "${GITHUB_REPOSITORY_OWNER:?GITHUB_REPOSITORY_OWNER is required}"
: "${GITHUB_REPOSITORY_NAME:?GITHUB_REPOSITORY_NAME is required}"
: "${GITHUB_RUNNER_PAT:?GITHUB_RUNNER_PAT must be a fine-grained, repository-scoped PAT}"

log() { echo "[bootstrap-runner] $*"; }
DEPLOYMENT_NAME="runner-bootstrap-${ENV_NAME}"
PLACEHOLDER_IMAGE="bootstrap.invalid/runner:unused"

# ---------------------------------------------------------------------------
# Stage 1 — application foundation (full bootstrap only)
#
# `azd provision` below needs both an azd environment that already carries the
# subscription/location/resource-group/principal values (nothing else seeds
# them on a clean operator machine or a fresh CI checkout) and the Foundry azd
# extension (the template provisions Foundry unconditionally).
# ---------------------------------------------------------------------------
if [[ "$SKIP_IMAGE_BUILD" == "false" ]]; then
  log "Stage 1/3: seeding the azd environment '${ENV_NAME}'"
  azd env select "$ENV_NAME" 2>/dev/null || azd env new "$ENV_NAME" --no-prompt
  azd env set AZURE_SUBSCRIPTION_ID "$AZURE_SUBSCRIPTION_ID" --environment "$ENV_NAME"
  azd env set AZURE_LOCATION "$LOCATION" --environment "$ENV_NAME"
  azd env set AZURE_RESOURCE_GROUP "$RESOURCE_GROUP" --environment "$ENV_NAME"
  azd env set AZURE_PRINCIPAL_ID "$AZURE_PRINCIPAL_ID" --environment "$ENV_NAME"

  # Meta-package that bundles the Foundry azd extensions (`azd ai agent ...`
  # and the azure.ai.* extensions azure.yaml declares in requiredVersions).
  # `--force` makes the install idempotent when it is already present.
  log "Stage 1/3: ensuring the microsoft.foundry azd extension is installed"
  azd ext install microsoft.foundry --force

  log "Stage 1/3: provisioning the application foundation without runner infrastructure"
  azd provision --environment "$ENV_NAME" --no-prompt

  log "Stage 1/3: creating runner identity, private ACR, and private endpoint"
  az deployment group create \
    --resource-group "$RESOURCE_GROUP" \
    --subscription "$AZURE_SUBSCRIPTION_ID" \
    --name "$DEPLOYMENT_NAME" \
    --template-file infra/bootstrap-runner.bicep \
    --parameters environmentName="$ENV_NAME" location="$LOCATION" \
                 githubRepoOwner="$GITHUB_REPOSITORY_OWNER" githubRepoName="$GITHUB_REPOSITORY_NAME" \
                 runnerImage="$PLACEHOLDER_IMAGE" githubPat='' deployRunnerJob=false \
    --only-show-errors >/dev/null
else
  log "Stage 1/3: skipping azd provision — PAT rotation must not reprovision the application foundation"
fi

if [[ "$SKIP_IMAGE_BUILD" == "true" ]]; then
  IMAGE_REF="$(az containerapp job show --resource-group "$RESOURCE_GROUP" \
    --subscription "$AZURE_SUBSCRIPTION_ID" \
    --name "job-intake-runner-${ENV_NAME}" \
    --query 'properties.template.containers[0].image' -o tsv 2>/dev/null || true)"
  [[ -n "$IMAGE_REF" ]] || {
    echo "--skip-image-build requires an existing runner job with an image." >&2
    exit 1
  }
else
  ACR_NAME="$(az deployment group show --resource-group "$RESOURCE_GROUP" --name "$DEPLOYMENT_NAME" \
    --subscription "$AZURE_SUBSCRIPTION_ID" \
    --query properties.outputs.AZURE_RUNNER_ACR_NAME.value -o tsv)"
  ACR_LOGIN_SERVER="$(az deployment group show --resource-group "$RESOURCE_GROUP" --name "$DEPLOYMENT_NAME" \
    --subscription "$AZURE_SUBSCRIPTION_ID" \
    --query properties.outputs.AZURE_RUNNER_ACR_LOGIN_SERVER.value -o tsv)"
  IMAGE_REF="${ACR_LOGIN_SERVER}/github-actions-runner:${IMAGE_TAG}"
fi

restore_acr_public_access() {
  if [[ "${ACR_PUBLIC_ACCESS_BEFORE:-}" == "Disabled" ]]; then
    log "Restoring ACR public network access to Disabled"
    az acr update --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --public-network-enabled false --only-show-errors >/dev/null
  fi
}

if [[ "$SKIP_IMAGE_BUILD" == "false" ]]; then
  ACR_PUBLIC_ACCESS_BEFORE="$(az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --query publicNetworkAccess -o tsv)"
  trap restore_acr_public_access EXIT INT TERM
  if [[ "$ACR_PUBLIC_ACCESS_BEFORE" == "Disabled" ]]; then
    log "Stage 2/3: temporarily enabling ACR public access for the documented bootstrap build path"
    az acr update --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --public-network-enabled true --only-show-errors >/dev/null
  fi
  log "Stage 2/3: building and pushing ${IMAGE_REF}"
  # RUNNER_SHA256 defaults to the verified v2.336.0 release digest baked into
  # the Dockerfile; it is passed through only when an operator has explicitly
  # reviewed and exported an override.
  BUILD_ARGS=()
  if [[ -n "${RUNNER_SHA256:-}" ]]; then
    log "Stage 2/3: using an explicit RUNNER_SHA256 override"
    BUILD_ARGS+=(--build-arg "RUNNER_SHA256=${RUNNER_SHA256}")
  fi
  az acr build --registry "$ACR_NAME" --resource-group "$RESOURCE_GROUP" \
    --image "github-actions-runner:${IMAGE_TAG}" \
    "${BUILD_ARGS[@]+"${BUILD_ARGS[@]}"}" \
    --file scripts/azure/runner/Dockerfile scripts/azure/runner
  restore_acr_public_access
  trap - EXIT INT TERM
else
  log "Stage 2/3: skipping image build; rotating the job secret only"
fi

log "Stage 3/3: creating/updating the event-driven runner job with a direct ACA secret"
az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --subscription "$AZURE_SUBSCRIPTION_ID" \
  --name "$DEPLOYMENT_NAME" \
  --template-file infra/bootstrap-runner.bicep \
  --parameters environmentName="$ENV_NAME" location="$LOCATION" \
               githubRepoOwner="$GITHUB_REPOSITORY_OWNER" githubRepoName="$GITHUB_REPOSITORY_NAME" \
               runnerImage="$IMAGE_REF" githubPat="$GITHUB_RUNNER_PAT" deployRunnerJob=true \
  --only-show-errors >/dev/null
unset GITHUB_RUNNER_PAT

log "Bootstrap complete. The private runner job uses ${IMAGE_REF}."
