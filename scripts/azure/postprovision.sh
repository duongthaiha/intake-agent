#!/usr/bin/env bash
# scripts/azure/postprovision.sh
# azd postprovision hook entrypoint (POSIX). Runs, in order:
#   1. ensure-hosted-agent-rbac.sh — Foundry/Search permissions only.
#   2. validate-mcp-foundry-bootstrap.sh — fail-closed tenant bootstrap contract.
# Deployment verification is intentionally absent: postprovision runs before
# azd deploy and may only reconcile pre-deploy-safe RBAC.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "━━━ postprovision: Hosted Agent RBAC reconciliation ━━━"
bash "${SCRIPT_DIR}/ensure-hosted-agent-rbac.sh"
echo "━━━ postprovision: MCP Foundry bootstrap contract ━━━"
bash "${SCRIPT_DIR}/validate-mcp-foundry-bootstrap.sh"
