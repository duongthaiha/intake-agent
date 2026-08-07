# Intake Agent Product Backlog

## Assumptions

| Assumption | Why It Matters | Validation Needed |
|---|---|---|
| Solution is delivered via Microsoft Foundry Agent Service, published natively to Microsoft Teams (no custom bot host for MVP) | Determines channel integration, identity, and networking work | Confirmed in `architecture.md` §1, ADR-001 |
| Data services are customer-owned Azure Cosmos DB (NoSQL), Azure Blob Storage, Azure AI Search, and Azure Service Bus, processed by Azure Functions workers | Drives Bicep modules, private endpoint scope, and RBAC design | Confirmed in `architecture.md` §1, §8.2, ADR-004, ADR-006 |
| Infrastructure is authored in Bicep and deployed with Azure Developer CLI (`azd`) | Required for repeatable provisioning across environments | Confirmed in `architecture.md` §18, §20 (Slice 1) |
| Both a network-baseline and a hardened (private-networking) deployment variant are supported until compliance selects one | Affects when private endpoints/VNet work becomes mandatory vs. optional | Open decision — `architecture.md` §21 ADR-008, §23 item 1 |
| Model, Azure region, and final production network topology are not yet finalised | Impacts quota, data residency, and Bicep parameterisation | Open decision — `architecture.md` §23 items 1–2 |
| Single Microsoft Entra tenant, single enterprise organisation, no public/multi-tenant access for MVP | Simplifies identity and authorisation scope | Confirmed in `architecture.md` §2.1–2.2 |

## POC Goal

Prove that a Python Hosted Agent, published natively to Microsoft Teams through Microsoft Foundry Agent Service, can guide a requester through structured intake, detect gaps and contradictions, route the result through human review, generate an approved document, and hand the approved request to a downstream system — while keeping deterministic authorization, validation, persistence, and audit logic outside model control, and while proving the deployment is repeatable (Bicep + `azd`) and privacy/security-shaped (managed identity, Key Vault, private data-service access) from the first milestone.

## Epic 1: Structured Requirements Capture

### User Story 1.1: Dynamic Intake Template

*As a user, I want the agent to use a structured template so that my request is captured consistently.*

**Acceptance Criteria**

- Agent loads a predefined intake template.
- Template supports mandatory and optional fields.
- Template structure can be customised for different use cases.
- Agent tracks completion status for each section.
- Template schemas are validated and versioned.
- Existing requests retain the template version used to create them.

**Priority:** Must Have (MVP)

### User Story 1.2: Interactive Data Collection

*As a user, I want the agent to ask me questions so that all relevant information is collected.*

**Acceptance Criteria**

- Agent identifies missing mandatory information.
- Agent asks follow-up questions.
- Agent continues until mandatory fields are completed.
- Agent summarises captured information before submission.

**Priority:** Must Have (MVP)

### User Story 1.3: Context-Aware Validation

*As a user, I want the agent to validate my inputs so that poor quality requests are reduced.*

**Acceptance Criteria**

- Detect incomplete submissions.
- Flag contradictory information.
- Validate required fields.
- Provide recommendations for missing content.
- Validation errors identify the affected field and the action needed.
- Low-confidence validation results are flagged for clarification or human review.

**Priority:** High

## Epic 2: Gap Analysis & Clarification

### User Story 2.1: Requirement Gap Detection

*As a user, I want the agent to identify information gaps so that a complete request can be produced.*

**Acceptance Criteria**

- Agent compares collected information against template.
- Missing fields are highlighted.
- Confidence score generated per section.
- Agent recommends additional questions.
- Confidence score meaning and calculation are documented.
- Gap-detection quality meets the release thresholds defined in Epic 7.

**Priority:** Must Have (MVP)

### User Story 2.2: Clarification Workflow

*As a user, I want the agent to request clarification automatically when information is insufficient.*

**Acceptance Criteria**

- Agent generates clarifying questions.
- User responses update template fields.
- Agent re-evaluates completeness after every response.
- Workflow stops only when minimum quality threshold is met.
- The quality threshold is measurable and versioned.
- Maximum clarification attempts and an escalation path are defined.
- Users can review and correct inferred information before proceeding.

**Priority:** High

## Epic 3: Output Generation

### User Story 3.1: Generate Structured Requirements Document

*As a user, I want the agent to generate a document so that requirements can be shared with stakeholders.*

**Acceptance Criteria**

- Generate Word/PDF output.
- Populate all collected fields into a defined format.
- Include gaps, assumptions, and open questions.
- Include metadata (date, owner, status).
- Generated content is traceable to captured inputs.
- Generation failures provide an actionable error and do not lose request data.
- Outputs meet the accessibility requirements defined in Epic 11.

**Priority:** Must Have (MVP)

### User Story 3.2: User Approval Process

*As a user, I want to review the output before it is finalised.*

**Acceptance Criteria**

- User reviews generated output.
- User can approve or request edits.
- Agent supports multiple review iterations.
- Final approval timestamp recorded.
- Each review iteration creates a versioned record.
- Approval authority is enforced by role.
- The approved version is immutable; later changes require a new review cycle.

**Priority:** Must Have (MVP)

## Epic 4: Persistence & Workflow

### User Story 4.1: Save Request

*As a system, I want to persist intake requests so they can be tracked and audited.*

**Acceptance Criteria**

- Store request data.
- Store conversation history.
- Store generated output documents.
- Provide unique request ID.
- Encrypt stored data in transit and at rest.
- Apply access, retention, export, and deletion policies defined in Epic 9.
- Backup and restoration procedures preserve request integrity.

**Priority:** Must Have (MVP)

### User Story 4.2: Request Lifecycle Management

*As a user, I want requests to move through defined states so progress can be tracked.*

The discussion explicitly referenced a ticket-like lifecycle with multiple stages.

**Proposed States**

- New
- In Review
- Awaiting User Feedback
- Approved
- Rejected
- Completed

**Acceptance Criteria**

- Status transitions are controlled.
- Audit trail maintained.
- Notifications generated when action is required.
- History retained.
- Allowed transitions and role permissions are defined in a state-transition matrix.
- Invalid transitions return an actionable error.
- Notification delivery failures are retried and visible to operators.

**Priority:** Must Have (MVP)

## Epic 5: Human-in-the-Loop Review

### User Story 5.1: Reviewer Workflow

*As a reviewer, I want to review captured requirements so that quality is maintained.*

**Acceptance Criteria**

- Reviewer can edit captured content.
- Reviewer can add comments.
- Reviewer can approve or reject.
- Reviewer feedback is stored.
- Reviewer permissions are enforced.
- Concurrent edits cannot silently overwrite changes.
- Review decisions identify the reviewer, version, timestamp, and rationale.

**Priority:** High

### User Story 5.2: Feedback Loop

*As a requester, I want reviewer feedback returned to me so I can resolve issues.*

**Acceptance Criteria**

- Feedback visible in request record.
- Agent converts comments into actionable questions.
- Agent guides user through resubmission.
- Feedback items have an owner and resolution status.
- Resolved feedback is traceable to the resulting field or document change.
- Reviewer feedback can be curated into the evaluation dataset through an approved process.

**Priority:** High

## Epic 6: Downstream Automation

### User Story 6.1: Trigger Follow-on Processes

The team discussed feeding approved outputs into downstream services or agents.

*As a system, I want approved requests to trigger automation so manual handoffs are reduced.*

**Acceptance Criteria**

- Trigger configurable workflow.
- Pass structured output payload.
- Support multiple target systems.
- Log execution results.
- Use authenticated, versioned integration contracts.
- Prevent duplicate downstream processing through idempotency controls.
- Expose failed deliveries for retry or manual recovery.

**Priority:** High

### User Story 6.2: Agent-to-Agent Handover

*As a platform, I want intake results to be consumed by other agents.*

**Acceptance Criteria**

- Structured JSON output.
- Standard schema definition.
- API-based integration.
- Error handling and retry capability.
- Schema compatibility and versioning rules are defined.
- Handover is authenticated, authorised, and traceable.
- Contract tests verify each supported consumer.

**Priority:** Future Release

## Epic 7: Evaluation & Quality

### User Story 7.1: Define Quality Metrics

*As a product owner, I want measurable quality criteria so that release decisions are evidence-based.*

**Acceptance Criteria**

- Define metric formulas for field capture accuracy, required-gap recall, false-positive gap rate, contradiction detection, clarification relevance, groundedness, completion rate, and reviewer acceptance.
- Define critical failure categories that always block release.
- Record metric results by model, prompt, template, schema, and evaluation-dataset version.
- Agree target thresholds after a documented baseline run.
- Publish a release scorecard with pass or fail status for every metric.

**Priority:** Must Have (MVP Release Gate)

### User Story 7.2: Versioned Evaluation Dataset

*As a quality owner, I want a representative benchmark dataset so that agent quality can be measured consistently.*

**Acceptance Criteria**

- Dataset includes complete, incomplete, contradictory, ambiguous, sensitive, multilingual where supported, and adversarial requests.
- Expected fields, gaps, contradictions, questions, and acceptable outputs are reviewed by domain experts.
- Dataset is versioned, access-controlled, and separated from production data unless explicit approval and redaction requirements are met.
- Training or prompt-development examples are separated from the release evaluation set.
- Dataset changes include reviewer approval and change history.

**Priority:** Must Have (MVP Release Gate)

### User Story 7.3: Automated and Human Evaluation

*As a release owner, I want repeatable automated and human evaluations so that regressions are detected before deployment.*

**Acceptance Criteria**

- Automated evaluation runs against the versioned benchmark for every release candidate.
- Human reviewers use a documented scoring rubric and blinded samples where practical.
- Results compare the release candidate with the current production baseline.
- Any critical failure or metric below its threshold blocks release.
- Evaluation results and reviewer decisions are retained for audit.

**Priority:** Must Have (MVP Release Gate)

## Epic 8: Testing & Quality Assurance

### User Story 8.1: Automated Functional Testing

*As an engineering team, we want automated tests so that deterministic product behavior remains correct.*

**Acceptance Criteria**

- Unit tests cover validation rules, confidence handling, schema validation, and lifecycle transitions.
- Integration tests cover persistence, document generation, notifications, and enabled downstream services.
- End-to-end tests cover intake, clarification, review, rejection, resubmission, approval, and recovery flows.
- Contract tests validate structured outputs and enabled APIs.
- Tests run in continuous integration and failures block release.

**Priority:** Must Have (MVP Release Gate)

### User Story 8.2: AI Failure and Regression Testing

*As a quality owner, I want AI-specific failure tests so that unsafe or unreliable behavior is detected.*

**Acceptance Criteria**

- Tests cover hallucinated fields, missed and falsely reported gaps, irrelevant or repeated questions, missed contradictions, and unsupported claims.
- Tests cover prompt injection, sensitive-data disclosure, malformed input, excessively long input, and hostile content.
- The agent fails safely when required services, models, or tools are unavailable.
- Non-deterministic scenarios use repeated runs or tolerance ranges defined by the evaluation framework.
- Critical regressions block release.

**Priority:** Must Have (MVP Release Gate)

### User Story 8.3: Non-functional and Accessibility Testing

*As a release owner, I want non-functional tests so that the product is usable and reliable under expected conditions.*

**Acceptance Criteria**

- Performance tests verify agreed response-time, throughput, concurrency, and document-size targets.
- Resilience tests verify timeout, retry, idempotency, duplicate prevention, and recovery behavior.
- Security tests verify authentication, authorisation, data isolation, and common prompt and application attack paths.
- Accessibility tests verify the target defined in Epic 11.
- Test evidence is attached to the release record.

**Priority:** Must Have (MVP Release Gate)

## Epic 9: Security, Privacy & Governance

### User Story 9.1: Identity and Access Control

*As a data owner, I want controlled access so that request information is only available to authorised users and services.*

**Acceptance Criteria**

- Authentication is required for requester, reviewer, administrator, and service access.
- A role-permission matrix covers viewing, editing, reviewing, approving, exporting, deleting, and administering requests.
- Access is denied by default and enforced at the request and document level.
- Authorisation decisions are covered by automated tests.
- Privileged access is recorded in the audit trail.

**Priority:** Must Have (MVP Release Gate)

### User Story 9.2: Data Protection and Lifecycle

*As a data owner, I want request data protected throughout its lifecycle so that privacy and compliance obligations are met.*

**Acceptance Criteria**

- Data classification identifies personal, confidential, and sensitive fields.
- Data is encrypted in transit and at rest.
- Retention, deletion, export, backup, restoration, and data-residency requirements are defined.
- Sensitive content is redacted from logs and evaluation data.
- Deletion covers primary data, generated documents, conversation history, and applicable backups according to policy.

**Priority:** Must Have (MVP Release Gate)

### User Story 9.3: AI and Configuration Governance

*As a governance owner, I want controlled AI configuration changes so that behavior is traceable and reversible.*

**Acceptance Criteria**

- Model, prompt, template, schema, policy, and evaluation-dataset versions are recorded for every generated output.
- Configuration changes require review, test evidence, and an audit record.
- System instructions and trusted context are isolated from untrusted user content.
- Prompt-injection attempts cannot override access controls or disclose protected information.
- An approved version can be restored without data loss.

**Priority:** Must Have (MVP Release Gate)

### User Story 9.4: Private Networking for Data Services

*As a security owner, I want customer-owned data services reachable only through private connectivity so that the platform is not exposed to the public internet.*

**Acceptance Criteria**

- Every data-bearing service (Cosmos DB, Blob Storage, Azure AI Search, Service Bus, Key Vault) has a defined VNet/subnet and private endpoint design.
- Private DNS zones are configured so service names resolve to private IPs for the Hosted Agent and Functions workers.
- Public network access is disabled on each service where the platform supports it, unless an approved exception exists.
- A developer-access decision (VPN, jumpbox, dev tunnel, or cloud-only) is documented for local development and CI/CD.
- Both the network-baseline and hardened deployment variants are represented in Bicep until the production topology is confirmed (Epic 12).
- Deployed app-to-database private connectivity is validated from the deployed host, not a developer machine.

**Owner:** Architecture / Security

**Priority:** Must Have (MVP Release Gate)

## Epic 10: Reliability, Observability & Operations

### User Story 10.1: Service Objectives and Telemetry

*As an operator, I want measurable service health so that failures and quality degradation are detected.*

**Acceptance Criteria**

- Define availability, latency, throughput, and recovery objectives for MVP.
- Structured logs, metrics, and traces use the request ID as a correlation identifier.
- Dashboards show service health, error rates, clarification-loop rates, evaluation trends, and model or token cost.
- Alerts have defined thresholds, owners, and response procedures.
- Telemetry excludes or redacts sensitive request content.

**Priority:** Must Have (MVP Release Gate)

### User Story 10.2: Failure Recovery

*As a user, I want requests to recover from interruption so that my work is not lost or duplicated.*

**Acceptance Criteria**

- Draft data is saved and can be resumed after session or service interruption.
- Timeout and retry limits are defined for model, storage, document, notification, and integration operations.
- Retried operations are idempotent and do not create duplicate requests, approvals, documents, or handovers.
- Partial failures have an explicit state and an actionable user or operator recovery path.
- Recovery events are recorded in the audit trail.

**Priority:** Must Have (MVP Release Gate)

### User Story 10.3: Safe Deployment and Rollback

*As a release owner, I want controlled deployments so that faulty changes can be limited and reversed.*

**Acceptance Criteria**

- Development, test, and production environments have controlled promotion.
- Continuous integration enforces automated tests, evaluation thresholds, and security checks.
- Risky model, prompt, template, and workflow changes support staged rollout or feature flags.
- Rollback procedures cover application and AI configuration versions.
- Operational runbooks define incident ownership, diagnosis, recovery, and communication.

**Priority:** Must Have (MVP Release Gate)

## Epic 11: Experience & Accessibility

### User Story 11.1: Usable and Accessible Intake

*As a requester, I want an accessible and recoverable intake experience so that I can complete a request without avoidable barriers.*

**Acceptance Criteria**

- Users can save, resume, cancel, and review progress before submission.
- Validation and service errors use clear language, identify the affected content, and explain recovery.
- Required, optional, inferred, and low-confidence fields are distinguishable.
- The user interface meets WCAG 2.2 AA for supported workflows.
- Keyboard-only and assistive-technology workflows are tested.

**Priority:** Must Have (MVP)

### User Story 11.2: Usability Validation

*As a product owner, I want usability evidence so that the workflow works for representative requesters and reviewers.*

**Acceptance Criteria**

- Representative requesters and reviewers complete defined MVP scenarios.
- Measure completion rate, time to complete, abandonment, clarification burden, and user satisfaction.
- Critical usability failures are resolved before release.
- Usability findings are prioritised and linked to backlog items.

**Priority:** Must Have (MVP Release Gate)

## Epic 12: Azure Infrastructure and Deployment

### User Story 12.1: Bicep Infrastructure Modules

*As a DevOps engineer, I want Azure resources defined in Bicep so that environments are repeatable and reviewable.*

**Acceptance Criteria**

- An `infra/` folder contains Bicep modules for Foundry project, Hosted Agent hosting, Cosmos DB, Blob Storage, Azure AI Search, Service Bus, Azure Functions, Key Vault, and monitoring resources.
- Parameters cover environment-specific values (region, SKU, network mode); no secrets are stored in parameter files.
- Modules are used once a resource group becomes too large to reason about as a single template.
- Outputs expose values required by application/`azd` configuration (endpoints, resource IDs, connection settings).
- Bicep linting and a `what-if`/preflight check run before deployment.

**Owner:** DevOps

**Priority:** Must Have (MVP Release Gate)

### User Story 12.2: Azure Developer CLI Deployment

*As a developer, I want one-command provisioning and deployment so that the POC and later environments are reproducible.*

**Acceptance Criteria**

- `azure.yaml` at the repository root maps the Hosted Agent and each Functions worker to its Azure host.
- `azd provision`, `azd deploy`, and `azd up` succeed end-to-end against a clean environment.
- Required `azd env` values are documented; no secrets are committed to `azd` environment files.
- Managed identity is used for Azure resource access; secrets that cannot use managed identity are stored in Key Vault.
- CI/CD (GitHub Actions with workload identity federation) provisions and deploys test and production environments per `architecture.md` §18 and §20 (Slice 1).

**Owner:** DevOps

**Priority:** Must Have (MVP Release Gate)

### User Story 12.3: Environment and Region Selection

*As an architecture owner, I want environment and region decisions recorded so infrastructure choices are traceable.*

**Acceptance Criteria**

- Target Azure region is selected after checking Foundry Hosted Agent, tool, data-residency, and quota support, preferring the region with the broadest required service availability.
- Baseline (public-adjacent) and hardened (private-networking) deployment variants are both representable from the same Bicep modules until compliance selects one (`architecture.md` ADR-008).
- Dev, test, and production environments have distinct parameter sets and controlled promotion.
- Region and environment decisions are recorded as architecture decisions (see Architecture Decisions section).

**Owner:** Architecture

**Priority:** High

## Epic 13: POC Demo Script and Guide

### User Story 13.1: End-to-End Demo Script

*As a presenter, I want a step-by-step demo script so that I can reliably demonstrate the intake workflow on demand.*

**Acceptance Criteria**

- Script drives the primary Teams workflow: intake, clarification, submission, review, feedback, approval, document generation, and downstream handover.
- Script lists prerequisites, environment setup, and required test fixtures (sample requester/reviewer accounts, seed template).
- Expected outputs and screenshots/recordings are captured so a presenter can immediately spot a broken demo.
- Script is validated against a deployed environment, not only a local build.

**Owner:** Product

**Priority:** Must Have (MVP)

### User Story 13.2: Demo Environment Readiness

*As a demo owner, I want a dedicated, resettable demo environment so that repeated demos do not carry stale or corrupted state.*

**Acceptance Criteria**

- Demo environment is provisioned through the same Bicep/`azd` pipeline as other environments.
- A reset procedure restores demo data and clears prior requests between sessions.
- Demo environment access is scoped to designated presenter identities.

**Owner:** DevOps

**Priority:** High

## Epic 14: Deployment and Success Criteria Verification

### User Story 14.1: Clean Environment Deployment Proof

*As a release owner, I want a verified clean-environment deployment so that the POC is proven repeatable, not hand-built.*

**Acceptance Criteria**

- `azd up` runs end-to-end against a clean environment and the result is captured as evidence.
- A post-deploy smoke test confirms the Teams workflow, Hosted Agent, and background workers are live.
- Private connectivity to Cosmos DB, Storage, Search, Service Bus, and Key Vault is validated from the deployed host, not a developer machine, for the hardened variant.

**Owner:** DevOps

**Priority:** Must Have (MVP Release Gate)

### User Story 14.2: Success Criteria Verification

*As a stakeholder, I want each POC success criterion checked against the deployed system so that go/no-go decisions are evidence-based.*

**Acceptance Criteria**

- Each success criterion from the POC Goal and provisional service objectives (`architecture.md` §3.1) is checked against the deployed system.
- Results are recorded alongside the Epic 7 evaluation scorecard and release evidence.
- Any unmet criterion is logged as a decision item or deferred-scope item, not silently dropped.

**Owner:** Product

**Priority:** Must Have (MVP Release Gate)

## Epic 15: Documentation of Architecture Decisions, Workflow Diagrams, and Operational Runbooks

### User Story 15.1: Architecture Decision Records

*As an engineering lead, I want architecture decisions documented and kept current so that the next team can build on this POC.*

**Acceptance Criteria**

- Architecture decisions and their recorded status (Accepted/Proposed) are kept current in `architecture.md` §21 as decisions are confirmed.
- Open decisions and validation spikes (`architecture.md` §23) are tracked to closure with an owner and target date.
- Architecture and workflow diagrams (component, sequence, and network topology) are committed alongside the backlog.

**Owner:** Architecture

**Priority:** Must Have (MVP)

### User Story 15.2: Operational Runbooks

*As an operator, I want runbooks so that I can deploy, rotate secrets, redeploy, and tear down the environment safely.*

**Acceptance Criteria**

- Runbook covers deploy, secret rotation, redeploy, rollback, and teardown procedures.
- Runbook documents what must change before production (e.g., finalising network topology, region, retention policy).
- Lessons learned from deployment and testing issues are captured and linked back to the relevant backlog item.

**Owner:** DevOps

**Priority:** Must Have (MVP Release Gate)

## Architecture Decisions

| Decision | Recommended Default | Status |
|---|---|---|
| IaC | Bicep (`infra/` folder, modules per resource group size) | Accepted — `architecture.md` ADR references §21 |
| Deployment | Azure Developer CLI with `azure.yaml` and `infra/` | Accepted |
| Data services | Customer-owned Cosmos DB, Blob Storage, Azure AI Search, Service Bus, processed by Azure Functions | Accepted — ADR-004, ADR-006 |
| Database/network access | Private endpoint + private DNS; public access disabled where supported | Proposed until production topology confirmed — ADR-008 |
| Credentials | Managed identity first; Key Vault for secrets that cannot use managed identity | Accepted |
| Production network topology | Baseline vs. hardened — pending security/compliance confirmation | Open — `architecture.md` §23 item 1 |
| Model and Azure region | Pending Foundry Hosted Agent, tool, data-residency, and quota check | Open — `architecture.md` §23 item 2 |
| Word/PDF generation runtime | Functions vs. Container Apps job — pending library/runtime constraint check | Open — `architecture.md` §23 item 5 |

## Azure Guardrails

- **Bicep:** all Azure resources are defined as Bicep modules under `infra/`; parameters carry environment-specific values; outputs feed application/`azd` configuration; linting and what-if checks run before deploy.
- **Azure Developer CLI:** `azure.yaml` maps every deployable service; `azd provision`, `azd deploy`, and `azd up` are supported; required `azd env` values are documented without committing secrets.
- **Private networking:** Cosmos DB, Blob Storage, Azure AI Search, Service Bus, and Key Vault use private endpoints and private DNS; public network access is disabled where supported; app-to-database connectivity is validated from the deployed host.
- **Identity and secrets:** managed identity is the default for service-to-service access; Key Vault holds any secret that cannot use managed identity; no secrets appear in source, Bicep parameter files, `azd` environment files, or backlog examples; RBAC is scoped per service-to-service dependency.
- **Region:** prefer the region with the broadest availability of required services (Foundry, Cosmos DB, Storage, Search, Service Bus, Functions, Key Vault).

## MVP Definition of Done

A Must Have (MVP) story is complete only when:

- Functional acceptance criteria pass.
- Required unit, integration, end-to-end, contract, security, resilience, performance, and accessibility tests pass.
- The release candidate meets all Epic 7 evaluation thresholds with no critical regression.
- Security, privacy, authorisation, audit, and data-lifecycle controls are verified.
- Operational telemetry, alerts, recovery procedures, and rollback procedures are available.
- Infrastructure is represented in Bicep and `azd` can provision and deploy the workload, or a story exists to close the gap.
- Database and data-service networking uses the private endpoint/private DNS design, with public access disabled where supported.
- A clean-environment deployment is verified and each POC success criterion is checked against the deployed system (Epic 14).
- A demo script and an operational runbook are documented, with architecture decisions and workflow diagrams committed (Epics 13 and 15).
- User-facing and operational documentation is current.
- Evidence is linked to the release record and approved by the accountable owner.
