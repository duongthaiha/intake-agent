# Intake Agent foundation

This repository contains the first deterministic foundation layer of the Intake
Agent MVP described in [`docs/architecture-design.md`](docs/architecture-design.md)
and [`docs/functional-requirements.md`](docs/functional-requirements.md).

## Included

- Python 3.12 `uv` workspace with independently versioned packages.
- Strict v1 requester/reviewer contracts and a shared agent behavior specification.
- Standard-library-only domain entities and policies for validation, gaps,
  contradictions, confidence, clarification limits, lifecycle, authorization,
  provenance, immutable revisions, and stable errors.
- Application handlers with optimistic concurrency and idempotent mutations.
- Atomic in-memory request, audit, outbox, and idempotency adapter.
- Azure Cosmos DB persistence with ETag concurrency, transactional projections,
  audit/outbox writes, and expiring idempotency records.
- Service Bus dispatch, deduplicating consumers, retry/dead-letter handling, and
  replay; immutable Blob evaluation evidence; and service-only worker hosts.
- Production requester/reviewer MCP surfaces with delegated JWT validation,
  bounded requests, probes, and allowlisted telemetry.
- Ephemeral local profile with seeded requester/reviewer/service principals and a
  successful contract-test handover stub.
- Official MCP Python SDK 2.x streamable-HTTP server.

The SDK 2.x public class is `MCPServer`; it replaces the earlier public
`mcp.server.fastmcp.FastMCP` name. In this repository, architecture references to
the local "FastMCP surface" mean the SDK's ergonomic MCP server API, currently
implemented with `MCPServer`, without changing the streamable-HTTP protocol or
tool contracts.

## Package boundaries

```text
intake-agent-contracts  -> pydantic only
intake-agent-behavior   -> Python standard library only
intake-domain           -> Python standard library only
intake-application      -> intake-domain
intake-persistence      -> intake-domain + Azure SDKs
intake-workers          -> contracts + application + domain + persistence
intake-mcp              -> contracts + application + domain + persistence + MCP SDK
```

Agent-facing contracts and behavior do not import application, persistence,
Azure SDK, credential, Foundry runtime, Teams, or channel implementations.
Automated AST boundary tests enforce these rules.

## Local setup

Install `uv`, then run:

```powershell
uv python install 3.12
uv sync --python 3.12 --all-packages
uv run intake-local
```

The local streamable-HTTP endpoint is `http://127.0.0.1:8000/mcp`. The server
uses fixed local-only principals (`requester-1`, `reviewer-1`, and a completion
worker); identity and role are intentionally absent from model-controlled tool
arguments. Each MCP tool takes one `request` object validated directly by its
strict versioned contract model. State is process-local and ephemeral. The Azure runtime is composed separately
and does not change the credential-free local profile.

Run all checks:

```powershell
uv run ruff check .
uv run mypy
uv run pytest
```

On Microsoft-managed workstations where direct PyPI TLS is blocked, point `uv` at
the configured package feed proxy. Repositories stored in OneDrive also need copy
mode because cloud files do not support uv's cache hardlinks:

```powershell
$env:UV_DEFAULT_INDEX = "https://packagefeedproxy.microsoft.io/pypi/simple/"
$env:UV_LINK_MODE = "copy"
uv sync --python 3.12 --all-packages
```

Azure credentials are created only in persistence/worker composition roots and
are never accepted through agent-facing models. Foundry deployment, Teams
publishing, and Azure infrastructure remain outside this repository layer.
