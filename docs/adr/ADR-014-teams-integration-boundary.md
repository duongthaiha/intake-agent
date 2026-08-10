# ADR-014: Teams Integration as Adapter Boundary

**Status:** Accepted  
**Date:** 2026-08-07  
**Deciders:** Morpheus, Neo, Trinity  

## Context

Teams publishing depends on Foundry Agent Service, Azure Bot Service, and Microsoft 365 tenant admin approval. These are external dependencies that may not be available during POC development or in CI.

## Decision

### Teams is an adapter, not a hard assumption

The system is designed with the following channel hierarchy:

1. **Primary (production):** Teams via Foundry Activity Protocol → Azure Bot Service  
2. **Development/CI:** Local HTTP endpoint or CLI adapter  
3. **Fallback:** Foundry portal web chat  

### Local demonstration path

A `LocalAdapter` in `src/intake_agent/adapter/local.py` provides:

```python
class LocalAdapter:
    """HTTP/CLI adapter for testing the vertical slice without Teams/Foundry."""

    async def handle_message(self, message: str, user_id: str = "local-user") -> str:
        """Process a message through the full command pipeline."""
        context = ActorContext(
            user_id=user_id,
            tenant_id="local-tenant",
            roles=frozenset(["requester"]),
            conversation_id="local-conv-1",
            activity_id=str(uuid4()),
            correlation_id=str(uuid4()),
            agent_identity="local-agent",
        )
        # Route through orchestrator → commands → domain → repositories
        ...
```

This adapter:
- Demonstrates the full vertical slice (create → capture → validate → persist → resume → submit).
- Runs with in-memory persistence (no Azure needed).
- Is used by Switch's integration tests.
- Can be exposed as a FastAPI endpoint for demo purposes.

### Neo's spike scope (`src/intake_teams/`)

Neo owns the Teams-specific spike:
- Validate Foundry Activity Protocol integration.
- Confirm Bot Service F0/S1 tier.
- Test Adaptive Card rendering.
- Validate tenant publishing flow.
- Document findings for Tank's Bicep implementation.

If the spike succeeds: the `FoundryAdapter` in `src/intake_agent/adapter/foundry.py` becomes the production channel.  
If the spike is blocked: the POC demonstrates via local HTTP + Foundry web chat. No architecture change needed.

## Consequences

- POC vertical slice is demonstrable without Teams/Foundry/Bot Service.
- No wasted effort if tenant publishing is delayed.
- Clean separation: channel adapters create `ActorContext`; domain logic is channel-agnostic.
