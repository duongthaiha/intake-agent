# ADR-013: Domain Entities and Thin Vertical Flow

**Status:** Accepted  
**Date:** 2026-08-07  
**Deciders:** Morpheus (Design Review), Trinity, Switch  

## Context

The POC must demonstrate the complete vertical flow: create → capture → validate → persist → resume → submit → review-ready. This ADR defines the domain entities and their relationships precisely enough for parallel implementation.

## Decision

### Core entities (in `intake_domain/entities/`)

```python
# request.py
@dataclass
class Request:
    request_id: str               # Deterministic: hash(tenant_id, conversation_id)
    tenant_id: str
    conversation_id: str
    requester_id: str
    status: RequestStatus         # Enum: NEW, IN_REVIEW, AWAITING_FEEDBACK, APPROVED, REJECTED, COMPLETED
    current_revision: int
    template_id: str
    template_version: str
    created_at: datetime
    updated_at: datetime
    etag: str                     # Cosmos ETag for optimistic concurrency

class RequestStatus(str, Enum):
    NEW = "new"
    IN_REVIEW = "in_review"
    AWAITING_FEEDBACK = "awaiting_feedback"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"

# revision.py
@dataclass
class RequestRevision:
    request_id: str
    revision: int
    fields: dict[str, FieldValue]
    gaps: list[Gap]
    quality_score: float | None
    agent_version: str
    prompt_version: str
    model_version: str
    template_version: str
    created_at: datetime
    immutable: bool               # True once submitted for review

# field_value.py
@dataclass
class FieldValue:
    field_path: str
    value: Any
    source_reference: str | None
    model_confidence: float | None
    validation_status: ValidationStatus  # VALID, INVALID, PENDING

# gap.py
@dataclass
class Gap:
    gap_id: str
    field_path: str
    category: GapCategory         # MISSING, CONTRADICTORY, AMBIGUOUS, LOW_CONFIDENCE
    severity: GapSeverity         # BLOCKING, WARNING
    status: GapStatus             # OPEN, RESOLVED, ACCEPTED

# review.py
@dataclass
class Review:
    review_id: str
    reviewer_id: str
    decision: ReviewDecision | None  # APPROVE, REJECT, REQUEST_CHANGES
    rationale: str
    decided_at: datetime | None

# workflow_event.py
@dataclass
class WorkflowEvent:
    event_id: str
    request_id: str
    revision: int
    actor_id: str
    actor_type: ActorType         # USER, AGENT, WORKER, ADMIN
    command_id: str
    prior_state: RequestStatus | None
    new_state: RequestStatus | None
    occurred_at: datetime
```

### Thin vertical flow (Slice 2 implementation order)

```
1. get_or_create_request
   - Derive request_id from tenant + conversation
   - If exists: load and return current state
   - If not: create Request(status=NEW, revision=1) + empty RequestRevision

2. propose_field_updates
   - Validate field paths against template schema
   - Validate values against field-level rules
   - Apply confidence policy (flag low-confidence as gaps)
   - Persist updated revision fields + new gaps
   - Emit RequestFieldsUpdated event to outbox

3. get_request_context
   - Load Request + current RequestRevision + gaps + allowed actions
   - Allowed actions derived from status + actor role

4. submit_for_review
   - Assert status == NEW or AWAITING_FEEDBACK
   - Assert all BLOCKING gaps resolved
   - Assert quality_score >= template threshold
   - Freeze revision (immutable=True)
   - Transition to IN_REVIEW
   - Emit RequestSubmitted event

5. record_review_decision (approve path)
   - Assert status == IN_REVIEW
   - Assert actor is assigned reviewer
   - Record Review with decision=APPROVE
   - Transition to APPROVED
   - Emit RequestApproved event
```

### Actor context (injected, never model-supplied)

```python
@dataclass
class ActorContext:
    user_id: str
    tenant_id: str
    roles: frozenset[str]         # From Entra claims
    conversation_id: str
    activity_id: str
    correlation_id: str           # Propagated trace context
    agent_identity: str           # Foundry managed identity
```

## Consequences

- Every entity is a plain dataclass with no Azure SDK dependency.
- The vertical flow is testable with in-memory repositories.
- Immutability of approved revisions is enforced at the domain layer.
- Actor context is constructed by the adapter, not by the model.
