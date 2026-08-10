# Command and Event Schemas

## Command envelope

All mutating commands share this envelope:

```json
{
  "command_id": "uuid-v4",
  "command_type": "propose_field_updates",
  "request_id": "deterministic-id",
  "expected_revision": 3,
  "correlation_id": "trace-correlation-uuid",
  "idempotency_key": "command_id",
  "actor": {
    "user_id": "entra-oid",
    "tenant_id": "entra-tid",
    "actor_type": "user",
    "agent_identity": "foundry-agent-msi-id"
  },
  "timestamp": "2026-08-07T16:00:00Z",
  "data": { }
}
```

### Idempotency

- `command_id` is the idempotency key for interactive commands.
- Replay within TTL (7 days interactive, 30 days async) returns the original result.
- The idempotency store uses `scopeId = request_id` as partition key.

### Optimistic concurrency

- `expected_revision` must match the current `Request.current_revision`.
- On mismatch, return `ConflictError` with the current revision state.
- ETag on the Cosmos document provides the physical concurrency guard.

## Commands

### propose_field_updates

```json
{
  "data": {
    "updates": [
      {
        "field_path": "project.name",
        "value": "Customer Portal Redesign",
        "source_reference": "user message turn 3",
        "model_confidence": 0.95
      }
    ]
  }
}
```

**Result (success):**
```json
{
  "status": "accepted",
  "revision": 4,
  "accepted_fields": ["project.name"],
  "rejected_fields": [],
  "new_gaps": [],
  "resolved_gaps": ["gap-001"]
}
```

**Result (partial):**
```json
{
  "status": "partial",
  "revision": 4,
  "accepted_fields": ["project.name"],
  "rejected_fields": [
    { "field_path": "budget.amount", "error_code": "INVALID_TYPE", "message": "Expected number" }
  ],
  "new_gaps": [
    { "gap_id": "gap-005", "field_path": "timeline.end_date", "category": "missing", "severity": "blocking" }
  ]
}
```

### submit_for_review

```json
{
  "data": {}
}
```

**Result (success):**
```json
{
  "status": "submitted",
  "revision": 4,
  "new_status": "in_review"
}
```

### record_review_decision

```json
{
  "data": {
    "decision": "approve",
    "rationale": "All fields verified and complete."
  }
}
```

## Error responses

All errors use a consistent structure:

```json
{
  "status": "error",
  "error_code": "CONFLICT",
  "message": "Expected revision 3 but current is 4",
  "current_revision": 4,
  "retry_eligible": true
}
```

| Error code | HTTP-equiv | Meaning |
|-----------|-----------|---------|
| `VALIDATION_ERROR` | 422 | Field/schema validation failed |
| `AUTHORIZATION_DENIED` | 403 | Actor lacks required role/permission |
| `CONFLICT` | 409 | Optimistic concurrency failure |
| `NOT_FOUND` | 404 | Request or resource not found |
| `INVALID_TRANSITION` | 422 | State machine rejects the transition |
| `PRECONDITION_FAILED` | 412 | Required conditions not met (e.g., blocking gaps) |
| `TRANSIENT_ERROR` | 503 | Retryable infrastructure failure |
| `PERMANENT_ERROR` | 500 | Non-retryable failure |

## Domain event envelope

```json
{
  "event_id": "uuid-v4",
  "event_type": "RequestFieldsUpdated",
  "event_version": "1.0",
  "request_id": "deterministic-id",
  "revision": 4,
  "correlation_id": "trace-correlation-uuid",
  "causation_id": "command-id-that-caused-this",
  "occurred_at": "2026-08-07T16:00:00.123Z",
  "actor": {
    "user_id": "entra-oid",
    "actor_type": "user"
  },
  "data": { }
}
```

### Event types

| Event | `data` payload |
|-------|---------------|
| `RequestCreated` | `{ "template_id", "template_version", "requester_id" }` |
| `RequestFieldsUpdated` | `{ "accepted_fields": [...], "resolved_gaps": [...], "new_gaps": [...] }` |
| `RequestSubmitted` | `{ "revision", "quality_score" }` |
| `ChangesRequested` | `{ "reviewer_id", "feedback": "..." }` |
| `RequestApproved` | `{ "reviewer_id", "revision", "rationale" }` |
| `RequestRejected` | `{ "reviewer_id", "revision", "rationale" }` |
| `DocumentGenerationRequested` | `{ "revision", "artifact_type": "word|pdf" }` |
| `DocumentGenerated` | `{ "artifact_id", "blob_uri", "checksum" }` |
| `DeliveryRequested` | `{ "target", "schema_version", "idempotency_key" }` |
| `DeliveryCompleted` | `{ "delivery_id", "target" }` |
| `DeliveryFailed` | `{ "delivery_id", "target", "failure_type": "transient|permanent", "attempts" }` |
| `RequestCompleted` | `{ "revision" }` |

### Consumer rules

- Ignore unknown fields (additive-compatible).
- Reject unknown `event_version` major (breaking).
- Deduplicate by `event_id`.
- Process at-least-once; idempotent effect.

## Correlation identifiers

| ID | Scope | Purpose |
|----|-------|---------|
| `correlation_id` | Cross-service trace | Ties all operations from one user action |
| `request_id` | Business entity | The intake request being processed |
| `command_id` | Single command | Idempotency key; causation source |
| `event_id` | Single event | Deduplication; audit reference |
| `activity_id` | Teams turn | Links to Teams conversation turn |
| `trace_id` | OpenTelemetry | Distributed trace propagation |
