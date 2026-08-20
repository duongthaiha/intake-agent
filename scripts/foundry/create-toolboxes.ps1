$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")

azd ai toolbox create intake-requester `
    --from-file (Join-Path $root "foundry\toolboxes\requester-toolbox.yaml")

azd ai toolbox create intake-reviewer `
    --from-file (Join-Path $root "foundry\toolboxes\reviewer-toolbox.yaml")
