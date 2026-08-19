# scripts/azure/postprovision.ps1
# azd postprovision hook entrypoint (Windows). Runs, in order:
#   1. ensure-hosted-agent-rbac.ps1 — narrow RBAC reconciliation for the
#      Hosted Agent runtime identity (previously an orphaned script that was
#      never invoked anywhere).
# Deployment verification is intentionally absent: postprovision runs before
# azd deploy and may only reconcile pre-deploy-safe RBAC.

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "━━━ postprovision: Hosted Agent RBAC reconciliation ━━━"
& "$scriptDir\ensure-hosted-agent-rbac.ps1"
if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
