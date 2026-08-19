# scripts/azure/postprovision.ps1
# azd postprovision hook entrypoint (Windows). Runs, in order:
#   1. ensure-hosted-agent-rbac.ps1 — Foundry/Search permissions only.
#   2. validate-mcp-foundry-bootstrap.ps1 — fail-closed tenant bootstrap contract.
# Deployment verification is intentionally absent: postprovision runs before
# azd deploy and may only reconcile pre-deploy-safe RBAC.

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "━━━ postprovision: Hosted Agent RBAC reconciliation ━━━"
& "$scriptDir\ensure-hosted-agent-rbac.ps1"
if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "━━━ postprovision: MCP Foundry bootstrap contract ━━━"
& "$scriptDir\validate-mcp-foundry-bootstrap.ps1"
if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
