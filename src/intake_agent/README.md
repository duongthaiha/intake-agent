# intake-agent Python Backend

Python backend for the Intake Agent — domain layer, persistence adapters, and local HTTP demo.

## Packages

| Package | Purpose |
|---------|---------|
| `intake_domain` | Pure domain — entities, repositories (protocols), commands, events, services |
| `intake_persistence` | Repository implementations: in-memory (local/CI) and Azure adapters (Cosmos, Blob, Service Bus) |
| `intake_agent` | Foundry Hosted Agent: config, adapters, orchestrator, FastAPI demo entrypoint |
| `intake_workers` | Azure Functions worker: outbox dispatcher, document/notification/integration workers |

## Quick start (local, no Azure required)

```bash
pip install -e ".[dev]"
uvicorn intake_agent.main:app --reload --port 8000
```

## Microsoft Foundry Hosted Agent

`hosted_main.py` is the direct-code deployment entry point. It uses Foundry's
OpenAI-compatible Responses protocol and Microsoft Agent Framework. The
platform-provided user/chat isolation keys scope all domain tools; caller
identity, request IDs, and roles are never accepted as model tool arguments.
The host provides `/health` and the AgentServer `/readiness` route.

The agent exposes deterministic tools for request context, one-field updates,
submission, and listing the current user's requests. Review decisions remain
unavailable until Foundry Activity/OBO claims can be mapped to verified reviewer
roles.

Hosted deployments require `INTAKE_HOSTED_TENANT_ID`. Durable state is required
outside local development unless a non-production smoke deployment explicitly
sets `INTAKE_ALLOW_EPHEMERAL_HOSTED_STATE=true`; production always rejects
in-memory persistence. Azure SDK clients use managed identity through
`DefaultAzureCredential`; no API keys are accepted. Foundry also injects
`FOUNDRY_PROJECT_ENDPOINT` and `AZURE_AI_MODEL_DEPLOYMENT_NAME`.

### Demo endpoints

```
POST /requests                          # Create or resume a request
GET  /requests?user_id=alice            # List requests
GET  /requests/{request_id}?user_id=alice   # Get context + gaps + allowed actions
POST /requests/{request_id}/fields      # Propose field updates
POST /requests/{request_id}/submit      # Submit for review
POST /requests/{request_id}/review      # Record review decision (approve/reject/request_changes)
GET  /health
```

Example end-to-end flow:

```bash
# 1. Create request
curl -X POST http://localhost:8000/requests \
     -H "Content-Type: application/json" \
     -d '{"user_id":"alice","conversation_id":"conv-1"}'

# 2. Fill fields (use request_id from above)
curl -X POST http://localhost:8000/requests/{request_id}/fields \
     -H "Content-Type: application/json" \
     -d '{"expected_revision":1,"updates":[
           {"field_path":"project.name","value":"Portal Redesign","model_confidence":0.95},
           {"field_path":"project.description","value":"Rebuild the portal","model_confidence":0.9},
           {"field_path":"requester.business_unit","value":"Engineering","model_confidence":0.88},
           {"field_path":"priority","value":"high","model_confidence":0.92},
           {"field_path":"budget.amount","value":50000},
           {"field_path":"timeline.target_date","value":"2026-12-31"}
         ]}'

# 3. Submit
curl -X POST http://localhost:8000/requests/{request_id}/submit \
     -H "Content-Type: application/json" \
     -d '{"expected_revision":2}'

# 4. Approve
curl -X POST http://localhost:8000/requests/{request_id}/review \
     -H "Content-Type: application/json" \
     -d '{"expected_revision":2,"decision":"approve","rationale":"Complete","reviewer_id":"bob"}'
```

## Architecture

- **Deterministic core:** all validation, lifecycle transitions, and gap detection run in domain code, not in prompts.
- **Actor context injected:** user identity comes from the channel adapter, never from model output.
- **Optimistic concurrency:** every mutating command carries `expected_revision`; the repository enforces ETag matching.
- **Idempotency:** commands carry a `command_id`; replays within TTL return the stored result.
- **Outbox pattern:** state changes and outbox items are persisted atomically; the dispatcher publishes to Service Bus separately.

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `INTAKE_PERSISTENCE_BACKEND` | `inmemory` | `inmemory` or `cosmos` |
| `INTAKE_SERVICEBUS_BACKEND` | `inmemory` | `inmemory` or `azure` |
| `INTAKE_BLOB_BACKEND` | `inmemory` | `inmemory` or `azure` |
| `INTAKE_COSMOS_ENDPOINT` | — | Required when backend=cosmos |
| `INTAKE_COSMOS_DATABASE` | `intake` | Cosmos database name |
| `INTAKE_COSMOS_REQUESTS_CONTAINER` | `requests` | `/requestId` aggregate, audit, and outbox container; production uses `request-state` |
| `INTAKE_COSMOS_TEMPLATES_CONTAINER` | `templates` | `/templateId` template container |
| `INTAKE_COSMOS_IDEMPOTENCY_CONTAINER` | `idempotency` | `/scopeId` TTL result container |
| `INTAKE_BLOB_ENDPOINT` | — | Required when blob backend=azure |
| `INTAKE_BLOB_CONTAINER_ARTIFACTS` | `request-artifacts` | Versioned artifact container |
| `INTAKE_SERVICEBUS_NAMESPACE` | — | Required when Service Bus backend=azure |
| `INTAKE_SERVICEBUS_QUEUE` | `domain-events` | Outbox destination queue; production uses `domain-events-durable` |
| `INTAKE_HOSTED_TENANT_ID` | — | Required outside local development |
| `AZURE_CLIENT_ID` | — | Deployed user-assigned managed identity client ID |
| `INTAKE_TEMPLATE_ID` | `general-intake-v1` | Default template for new requests |
| `INTAKE_ENVIRONMENT` | `local` | Environment name for structured logging |

Azure adapters use `DefaultAzureCredential` with the configured user-assigned
managed identity. All three backends must be durable outside local development;
startup fails closed rather than selecting an in-memory fallback.

Physical resource names are environment configuration. The deployed mapping
uses `request-state` because the legacy `requests` container has immutable
partition key `/tenantId`, and uses `domain-events-durable` because the legacy
queue lacks duplicate detection. Do not replace these mappings with the local
defaults.

The Azure Functions deployment archive must include the `intake_domain` and
`intake_persistence` packages beside `src/intake_workers/function_app.py`.
Zipping `src/intake_workers` alone is not a valid production worker package.
Worker requirements also include Pydantic for the domain models and aiohttp for
Azure Identity's asynchronous transport.

## Linting / type checking

```bash
python -m ruff check src/intake_domain src/intake_persistence src/intake_agent src/intake_workers
python -m mypy src/intake_domain
python -m lint-imports   # import-linter boundary checks
```
