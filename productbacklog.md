# Intake Agent Product Backlog

## Assumptions

| Assumption | Why It Matters | Validation Needed |
|---|---|---|
| Solution is delivered via Microsoft Foundry Agent Service, published natively to Microsoft Teams (no custom bot host for MVP) | Determines channel integration, identity, and networking work | Confirmed in `architecture.md` §1, ADR-001 |
| Data services are customer-owned Azure Cosmos DB (NoSQL), Azure Blob Storage, Azure AI Search, and Azure Service Bus; Azure Functions workers are the proposed asynchronous processing runtime | Drives Bicep modules, private endpoint scope, and RBAC design | Data services confirmed by `architecture.md` ADR-004; worker runtime proposed by ADR-006 |
| Infrastructure is authored in Bicep and deployed with Azure Developer CLI (`azd`) | Required for repeatable provisioning across environments | Accepted in `architecture.md` ADR-011 |
| Both a network-baseline and a hardened (private-networking) deployment variant are supported until compliance selects one | Requires both variants to remain deployable while leaving the final production selection open | Variant support accepted by `architecture.md` ADR-008; selection open in §23 item 1 |
| Model, Azure region, and final production network topology are not yet finalised | Impacts quota, data residency, and Bicep parameterisation | Open decision — `architecture.md` §23 items 1–2 |
| Single Microsoft Entra tenant, single enterprise organisation, no public/multi-tenant access for MVP | Simplifies identity and authorisation scope | Confirmed in `architecture.md` §2.1–2.2 |

## POC Goal

Prove that a Python Hosted Agent, published natively to Microsoft Teams through Microsoft Foundry Agent Service, can guide a requester through structured intake, detect gaps and contradictions, route the result through human review, generate an approved document, and validate handover through a versioned downstream contract — while keeping deterministic authorization, validation, persistence, and audit logic outside model control, and while proving the deployment is repeatable (Bicep + `azd`) and privacy/security-shaped (managed identity, Key Vault, private data-service access) from the first milestone.

### POC Success Criteria

| ID | Criterion | Required Evidence | Accountable Owner |
|---|---|---|---|
| POC-01 | A requester completes intake, clarification, submission, reviewer feedback, resubmission, and approval in Teams without an administrator changing data manually | Recorded end-to-end test and demo evidence from a deployed environment | Product |
| POC-02 | Every accepted field update is persisted before success is shown; an interrupted session resumes from the persisted request | Integration and recovery test evidence | Engineering |
| POC-03 | Only an assigned reviewer or authorised administrator can approve or reject; the approved revision is immutable | Authorisation, state-transition, and concurrency test evidence | Security |
| POC-04 | Word/PDF artifacts are generated only from the immutable approved revision and retain source/version metadata | Artifact contract test and deployed workflow evidence | Engineering |
| POC-05 | One approved request is delivered through the versioned downstream contract to either the selected first integration or an authenticated contract-test stub, without duplicate effects on retry | Contract, idempotency, and deployed smoke-test evidence | Engineering |
| POC-06 | Model-facing code cannot import repositories, Azure SDK clients, credential providers, or mutable identity implementations; the Hosted Agent and state-changing workers use the same approved `intake-domain` version | Import-boundary CI results and release manifest | Architecture |
| POC-07 | `azd up` provisions and deploys a clean environment from Bicep, and deployed workloads reach customer-owned data services through the selected private-endpoint topology | Deployment log, Bicep preflight result, DNS/connectivity evidence | DevOps |
| POC-08 | Epic 7 quality thresholds pass with no critical security or data-integrity failure, and the release baseline for the provisional service objectives in `architecture.md` §3.1 is met | Signed evaluation scorecard, performance results, frozen-baseline record, and approval record | Product |

POC criteria and thresholds are frozen before release-candidate evaluation begins. A scope or threshold change creates a new approved baseline and requires a new release candidate and complete evaluation; the failed result remains in the release evidence.

## Accountable Ownership

The owner type is accountable for acceptance and evidence; delivery may involve additional disciplines.

| Stories | Owner Type |
|---|---|
| 1.1, 1.2 | Product |
| 1.3 | Engineering |
| 2.1, 2.2 | Product |
| 3.1 | Engineering |
| 3.2 | Product |
| 4.1 | Data |
| 4.2 | Engineering |
| 5.1, 5.2 | Product |
| 6.1 | Engineering |
| 6.2 | Architecture |
| 7.1 | Product |
| 7.2 | Data |
| 7.3 | Product |
| 8.1 | Engineering |
| 8.2 | Security |
| 8.3 | Engineering |
| 8.4 | Architecture |
| 9.1 | Security |
| 9.2 | Data |
| 9.3, 9.4 | Security |
| 10.1 | DevOps |
| 10.2 | Engineering |
| 10.3 | DevOps |
| 11.1, 11.2 | Product |
| 12.1, 12.2 | DevOps |
| 12.3 | Architecture |
| 13.1 | Product |
| 13.2, 14.1 | DevOps |
| 14.2 | Product |
| 15.1 | Architecture |
| 15.2 | DevOps |

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

### User Story 3.1: Generate Approved Requirements Document

*As a user, I want the agent to generate a document from the approved revision so that requirements can be shared with stakeholders.*

**Acceptance Criteria**

- Generate Word/PDF output only after an assigned reviewer or authorised administrator approves the revision.
- Populate the immutable approved revision into a defined format.
- Include gaps, assumptions, and open questions.
- Include metadata (date, owner, status).
- Generated content is traceable to captured inputs.
- Generation failures provide an actionable error and do not lose request data.
- Outputs meet the accessibility requirements defined in Epic 11.

**Priority:** Must Have (MVP)

### User Story 3.2: Pre-Submission Review and Reviewer Approval

*As a requester, I want to review the captured requirements before submission and receive an authorised review decision so that errors can be corrected before finalisation.*

**Acceptance Criteria**

- Requester reviews and corrects captured requirements before submitting an immutable revision.
- Assigned reviewer or authorised administrator can approve, reject, or request changes; the requester cannot self-approve unless policy explicitly grants that role.
- Requested changes create a new immutable revision and review iteration.
- Final approval timestamp recorded.
- Each review iteration creates a versioned record.
- Approval authority is enforced by role.
- The approved revision is immutable; later changes require a new revision and review cycle.

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

- Reviewer cannot edit the requester's captured content; the reviewer requests changes against an immutable revision.
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
- For the POC, deliver to the selected first integration or an authenticated contract-test stub; selecting and productionising a real downstream target remains an explicit architecture decision.

**Priority:** Must Have (POC)

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

### User Story 8.4: Deterministic Package and Dependency Boundaries

*As an architecture owner, I want enforceable package boundaries so that model-facing code cannot bypass deterministic authorization, validation, persistence, or identity controls.*

**Acceptance Criteria**

- The repository produces a private, versioned `intake-domain` Python package shared by the Hosted Agent and all state-changing workers.
- CI import-boundary contracts fail when channel/orchestration code imports persistence modules, repositories, Azure SDK clients, credential providers, or mutable identity implementations.
- The domain layer contains no Foundry-specific types and depends only on the Python standard library and approved domain-only dependencies.
- The package is built once per release; the Hosted Agent and state-changing workers are promoted with the same approved version.
- Release evidence records the package version for every deployed component and fails promotion when versions are incompatible.

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

**Owner:** Security (Architecture consulted)

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

- An `infra/` folder contains Bicep modules for the Foundry project, Hosted Agent hosting, Azure Bot Service resource/association where supported, Cosmos DB, Blob Storage, Azure AI Search, Service Bus, Azure Functions, the private Container Apps evaluation job, evaluation evidence storage, Key Vault, monitoring, networking, workload identities, and the dedicated notification Entra application.
- Parameters cover environment-specific values (region, SKU, network mode); no secrets are stored in parameter files.
- Separate modules define each independently deployed or permission-scoped resource group: identity, network/private DNS, data services, messaging, agent/worker compute, evaluation, and observability.
- Outputs expose values required by application/`azd` configuration (endpoints, resource IDs, connection settings).
- Bicep linting and a `what-if`/preflight check run before deployment.
- Bicep applies required naming, tags, diagnostics, RBAC, budgets, locks, and Azure Policy assignments consistently by environment.
- A component/provisioner matrix identifies whether each resource or deployable component is created by Bicep, Foundry publishing, `azd`, or Microsoft 365 administration; no architecture component is left without an owner and provisioning path.

**Owner:** DevOps

**Priority:** Must Have (MVP Release Gate)

### User Story 12.2: Azure Developer CLI Deployment

*As a developer, I want one-command provisioning and deployment so that the POC and later environments are reproducible.*

**Acceptance Criteria**

- `azure.yaml` at the repository root maps every source-deployed component to its Azure host, including the Hosted Agent, Functions workers, and Container Apps evaluation job; the component/provisioner matrix records resources handled by Foundry publishing or Microsoft 365 administration instead.
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

- Script drives the primary Teams workflow: intake, clarification, submission, review, feedback, approval, document generation, and handover through the versioned downstream contract to the selected integration or contract-test stub.
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
- Any unmet mandatory POC criterion blocks that release candidate. A scope or threshold change requires Product, Architecture, and Security approval, a new frozen baseline, and a new candidate evaluation; the original failure remains in the release record.

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
| IaC | Bicep (`infra/` folder, modules by independently deployed or permission-scoped concern) | Accepted — ADR-011 |
| Deployment | Azure Developer CLI with `azure.yaml` and `infra/`; GitHub Actions invokes the same deployment contract | Accepted — ADR-011 |
| Customer-owned data services | Cosmos DB, Blob Storage, Azure AI Search, and Service Bus | Accepted — ADR-004 |
| Asynchronous worker runtime | Azure Functions | Proposed — ADR-006 |
| Deployment variants | Maintain baseline and hardened variants until compliance selects one | Accepted — ADR-008 |
| Data-service network access | Private endpoints + private DNS in both variants; public access disabled where supported | Accepted architecture principle and §14 requirement |
| Credentials | Managed identity first; Key Vault for exceptional secrets | Accepted architecture principle and §13 requirement |
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
- Infrastructure is represented in Bicep and `azd` successfully provisions and deploys the workload from a clean environment.
- Database and data-service networking uses the private endpoint/private DNS design, with public access disabled where supported.
- A clean-environment deployment is verified and each POC success criterion is checked against the deployed system (Epic 14).
- A demo script and an operational runbook are documented, with architecture decisions and workflow diagrams committed (Epics 13 and 15).
- User-facing and operational documentation is current.
- Evidence is linked to the release record and approved by the accountable owner.
