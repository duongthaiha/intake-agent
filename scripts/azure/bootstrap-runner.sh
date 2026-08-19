#!/usr/bin/env bash
# Bootstrap the private runner outside azd provision. Stages are idempotent:
# registry, image build/push, application foundation, then ACA Job creation.
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
#   INTAKE_MCP_APP_CLIENT_ID  — required for a full bootstrap; produced by
#                               bootstrap-prompt-intake-auth.sh

set -euo pipefail

ENV_NAME="${AZURE_ENV_NAME:-dev}"
LOCATION="${AZURE_LOCATION:-eastus2}"
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-rg-intake-${ENV_NAME}}"
IMAGE_TAG="runner-$(git rev-parse --short=12 HEAD)"
MCP_IMAGE_TAG="mcp-$(git rev-parse --short=12 HEAD)"
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
if [[ "$SKIP_IMAGE_BUILD" == "false" ]]; then
  : "${INTAKE_MCP_APP_CLIENT_ID:?INTAKE_MCP_APP_CLIENT_ID is required for full bootstrap}"
  if ! az group show \
    --name "$RESOURCE_GROUP" \
    --subscription "$AZURE_SUBSCRIPTION_ID" >/dev/null 2>&1; then
    echo "Resource group '$RESOURCE_GROUP' must exist before bootstrap." >&2
    echo "Create it through the approved subscription-level process, then retry." >&2
    exit 1
  fi
fi

log() { echo "[bootstrap-runner] $*"; }
DEPLOYMENT_NAME="runner-bootstrap-${ENV_NAME}"
PLACEHOLDER_IMAGE="bootstrap.invalid/runner:unused"

# ---------------------------------------------------------------------------
# Stage 1 — seed environment and create the registry (full bootstrap only)
#
# `azd provision` below needs both an azd environment that already carries the
# subscription/location/resource-group/principal values (nothing else seeds
# them on a clean operator machine or a fresh CI checkout) and the Foundry azd
# extension (the template provisions Foundry unconditionally).
# ---------------------------------------------------------------------------
if [[ "$SKIP_IMAGE_BUILD" == "false" ]]; then
  log "Stage 1/4: seeding the azd environment '${ENV_NAME}'"
  azd env select "$ENV_NAME" 2>/dev/null || azd env new "$ENV_NAME" --no-prompt
  azd env set AZURE_SUBSCRIPTION_ID "$AZURE_SUBSCRIPTION_ID" --environment "$ENV_NAME"
  azd env set AZURE_LOCATION "$LOCATION" --environment "$ENV_NAME"
  azd env set AZURE_RESOURCE_GROUP "$RESOURCE_GROUP" --environment "$ENV_NAME"
  azd env set AZURE_PRINCIPAL_ID "$AZURE_PRINCIPAL_ID" --environment "$ENV_NAME"

  # Meta-package that bundles the Foundry azd extensions (`azd ai agent ...`
  # and the azure.ai.* extensions azure.yaml declares in requiredVersions).
  # `--force` makes the install idempotent when it is already present.
  log "Stage 1/4: ensuring the microsoft.foundry azd extension is installed"
  azd ext install microsoft.foundry --force

  log "Stage 1/4: creating the runner identity and bootstrap-accessible ACR"
  az deployment group create \
    --resource-group "$RESOURCE_GROUP" \
    --subscription "$AZURE_SUBSCRIPTION_ID" \
    --name "$DEPLOYMENT_NAME" \
    --template-file infra/bootstrap-runner.bicep \
    --parameters environmentName="$ENV_NAME" location="$LOCATION" \
                 githubRepoOwner="$GITHUB_REPOSITORY_OWNER" githubRepoName="$GITHUB_REPOSITORY_NAME" \
                 runnerImage="$PLACEHOLDER_IMAGE" githubPat='' deployRunnerJob=false \
                 deployAcrPrivateEndpoint=false acrAllowPublicNetworkAccessForBootstrap=true \
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
  if [[ -n "${ACR_NAME:-}" ]]; then
    log "Restoring ACR public network access to Disabled"
    az acr update --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --public-network-enabled false --only-show-errors >/dev/null
  fi
}

if [[ "$SKIP_IMAGE_BUILD" == "false" ]]; then
  trap restore_acr_public_access EXIT INT TERM
  ACR_PUBLIC_ACCESS="$(az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --query publicNetworkAccess -o tsv)"
  if [[ "$ACR_PUBLIC_ACCESS" == "Disabled" ]]; then
    log "Stage 2/4: temporarily enabling ACR public access for the documented bootstrap build path"
    az acr update --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --public-network-enabled true --only-show-errors >/dev/null
  fi
  log "Stage 2/4: building and pushing ${IMAGE_REF}"
  # RUNNER_SHA256 defaults to the verified v2.336.0 release digest baked into
  # the Dockerfile; it is passed through only when an operator has explicitly
  # reviewed and exported an override.
  BUILD_ARGS=()
  if [[ -n "${RUNNER_SHA256:-}" ]]; then
    log "Stage 2/4: using an explicit RUNNER_SHA256 override"
    BUILD_ARGS+=(--build-arg "RUNNER_SHA256=${RUNNER_SHA256}")
  fi
  az acr build --registry "$ACR_NAME" --resource-group "$RESOURCE_GROUP" \
    --image "github-actions-runner:${IMAGE_TAG}" \
    "${BUILD_ARGS[@]+"${BUILD_ARGS[@]}"}" \
    --file scripts/azure/runner/Dockerfile scripts/azure/runner
  RUNNER_IMAGE_DIGEST="$(
    az acr repository show \
     --name "$ACR_NAME" \
     --image "github-actions-runner:${IMAGE_TAG}" \
     --query digest \
     --output tsv
  )"
  IMAGE_REF="${ACR_LOGIN_SERVER}/github-actions-runner@${RUNNER_IMAGE_DIGEST}"

  log "Stage 2/4: building prompt-intake-mcp:${MCP_IMAGE_TAG}"
  az acr build --registry "$ACR_NAME" --resource-group "$RESOURCE_GROUP" \
    --image "prompt-intake-mcp:${MCP_IMAGE_TAG}" \
    --file src/intake_mcp/Dockerfile .
  MCP_IMAGE_DIGEST="$(
    az acr repository show \
      --name "$ACR_NAME" \
      --image "prompt-intake-mcp:${MCP_IMAGE_TAG}" \
      --query digest \
      --output tsv
  )"
  MCP_IMAGE_REF="${ACR_LOGIN_SERVER}/prompt-intake-mcp@${MCP_IMAGE_DIGEST}"

  log "Stage 3/4: provisioning the application foundation and private MCP runtime"
  azd env set INTAKE_MCP_APP_CLIENT_ID "$INTAKE_MCP_APP_CLIENT_ID" --environment "$ENV_NAME"
  azd env set INTAKE_MCP_IMAGE "$MCP_IMAGE_REF" --environment "$ENV_NAME"
  azd provision --environment "$ENV_NAME" --no-prompt
else
  log "Stage 2/4: skipping image build and application provision; rotating the job secret only"
fi

log "Stage 4/4: creating the private endpoint and event-driven runner job"
az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --subscription "$AZURE_SUBSCRIPTION_ID" \
  --name "$DEPLOYMENT_NAME" \
  --template-file infra/bootstrap-runner.bicep \
  --parameters environmentName="$ENV_NAME" location="$LOCATION" \
               githubRepoOwner="$GITHUB_REPOSITORY_OWNER" githubRepoName="$GITHUB_REPOSITORY_NAME" \
               runnerImage="$IMAGE_REF" githubPat="$GITHUB_RUNNER_PAT" deployRunnerJob=true \
               deployAcrPrivateEndpoint=true acrAllowPublicNetworkAccessForBootstrap=false \
  --only-show-errors >/dev/null
restore_acr_public_access
trap - EXIT INT TERM
unset GITHUB_RUNNER_PAT

log "Bootstrap complete. The private runner job uses ${IMAGE_REF}."
