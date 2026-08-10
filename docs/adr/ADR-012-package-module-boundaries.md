# ADR-012: Python Package and Module Boundaries

**Status:** Accepted  
**Date:** 2026-08-07  
**Deciders:** Morpheus (Design Review), Trinity, Neo, Tank, Switch  

## Context

The architecture defines five logical dependency layers (§7.3). This ADR maps them to concrete Python packages, file paths, and ownership boundaries so parallel implementation can proceed without merge conflicts.

## Decision

### Repository Python structure

```
pyproject.toml                  # Root manifest — defines workspace and shared tooling
src/
  intake_agent/                 # Foundry Hosted Agent (channel + orchestration)
    __init__.py
    adapter/                    # Channel/identity adapter (Activity → actor context)
    orchestrator/               # Conversation orchestrator + tool definitions
    presenter/                  # Response formatting for Teams
    config.py                   # Runtime config loading from env
  intake_domain/                # Pure domain package (no IO, no Azure SDK)
    __init__.py
    commands/                   # Command models + handlers
    events/                     # Domain event models
    entities/                   # Aggregate roots, value objects
    repositories/               # Abstract repository protocols (ABCs)
    services/                   # Domain services (validation, lifecycle, quality)
    errors.py                   # Domain error hierarchy
  intake_persistence/           # Cosmos/Blob/Bus adapters (implements repository protocols)
    __init__.py
    cosmos/                     # Cosmos DB repository implementations
    blob/                       # Blob storage adapter
    servicebus/                 # Outbox dispatcher + Service Bus publisher
    inmemory/                   # In-memory implementations for tests
  intake_workers/               # Azure Functions worker package
    __init__.py
    function_app.py             # Functions entry point
    document_worker.py
    notification_worker.py
    integration_worker.py
    completion_worker.py
    outbox_dispatcher.py
  intake_teams/                 # Teams adapter spike / publishing assets
    __init__.py
    manifest/                   # Teams app manifest templates
    cards/                      # Adaptive Card templates
    docs/                       # Teams integration documentation
tests/                          # All test code
  unit/
  component/
  contract/
  integration/
  e2e/
  fixtures/
  conftest.py
```

### Dependency rules (enforced by import-linter)

| Package | May import | Must NOT import |
|---------|-----------|-----------------|
| `intake_domain` | Python stdlib, `pydantic` | Any Azure SDK, `intake_persistence`, `intake_agent`, `intake_workers`, `intake_teams` |
| `intake_persistence` | `intake_domain`, Azure SDK (`azure-cosmos`, `azure-storage-blob`, `azure-servicebus`) | `intake_agent`, `intake_workers`, `intake_teams` |
| `intake_agent` | `intake_domain`, `intake_persistence`, Foundry SDK | `intake_workers`, `intake_teams` |
| `intake_workers` | `intake_domain`, `intake_persistence`, Azure Functions SDK | `intake_agent`, `intake_teams` |
| `intake_teams` | None of the above (standalone spike) | All other `intake_*` packages |

### Build and packaging

- Single `pyproject.toml` at repo root using a src-layout.
- `intake_domain` is built as an independent wheel for version-pinned bundling.
- All other packages reference `intake_domain` as a dependency.
- CI builds the domain wheel first, then installs the full workspace for linting/testing.

### Ownership (non-overlapping)

| Path | Owner |
|------|-------|
| `pyproject.toml`, `src/intake_agent/**`, `src/intake_domain/**`, `src/intake_persistence/**`, `src/intake_workers/**` | Trinity |
| `src/intake_teams/**` | Neo |
| `azure.yaml`, `infra/**`, `.github/workflows/**`, deployment scripts | Tank |
| `tests/**`, evaluation fixtures, quality config (`.coveragerc`, `pytest.ini`) | Switch |

## Consequences

- Parallel work proceeds without path conflicts.
- Import-linter CI contract enforces architectural layering from first commit.
- In-memory repository implementations allow full domain + command testing without Azure.
- Domain package extraction to a separate repo is structurally trivial.
