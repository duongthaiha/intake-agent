#!/usr/bin/env bash
# scripts/azure/postprovision.sh
# azd postprovision hook entrypoint (POSIX). Runs, in order:
#   1. ensure-hosted-agent-rbac.sh — narrow RBAC reconciliation for the
#      Hosted Agent runtime identity (previously an orphaned script that was
#      never invoked anywhere).
# Deployment verification is intentionally absent: postprovision runs before
# azd deploy and may only reconcile pre-deploy-safe RBAC.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "━━━ postprovision: Hosted Agent RBAC reconciliation ━━━"
bash "${SCRIPT_DIR}/ensure-hosted-agent-rbac.sh"
