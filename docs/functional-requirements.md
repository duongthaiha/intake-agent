# Intake Agent Product Backlog

## Assumptions

| Assumption | Why It Matters | Validation Needed |
|---|---|---|
| Solution is delivered via Microsoft Foundry Agent Service, with Python Hosted Agent and Prompt Agent variants published natively to Microsoft Teams (no custom bot host for MVP) | Determines channel integration, identity, portability, and networking work | Confirmed in `architecture-design.md` §1, ADR-001 and ADR-017 |
| Hosted Agent and Prompt Agent are parallel orchestration adapters over shared requester/reviewer MCP contracts and deterministic services | Prevents business logic, authorization, persistence, and workflow behavior from diverging by agent type | Accepted in `architecture-design.md` ADR-016 and ADR-017; each variant must pass capability and parity gates |
| Data services are customer-owned Azure Cosmos DB (NoSQL), Azure Blob Storage, Azure AI Search, and Azure Service Bus; Azure Functions workers are the proposed asynchronous processing runtime | Drives Bicep modules, private endpoint scope, and RBAC design | Data services confirmed by `architecture-design.md` ADR-004; worker runtime proposed by ADR-006 |
| Infrastructure is authored in Bicep and deployed with Azure Developer CLI (`azd`) | Required for repeatable provisioning across environments | Accepted in `architecture-design.md` ADR-011 |
| Both a baseline variant (public Foundry access with private customer data services) and a hardened variant (private Foundry and private customer data services) are supported until compliance selects one | Requires both variants to remain deployable while leaving the final production selection open | Variant support accepted by `architecture-design.md` ADR-008; selection open in §23 item 1 |
| Model, Azure region, and final production network topology are not yet finalised | Impacts quota, data residency, and Bicep parameterisation | Open decision — `architecture-design.md` §23 items 1–2 |
| Single Microsoft Entra tenant, single enterprise organisation, no public/multi-tenant access for MVP | Simplifies identity and authorisation scope | Confirmed in `architecture-design.md` §2.1–2.2 |
| A local development profile may use in-memory substitutes for conversation history and external services; deployed environments continue to use customer-owned Azure services | Enables fast, offline development without weakening deployed persistence, security, or release evidence | Local substitutes must implement the same domain contracts and must not be used as production evidence |



## POC Goal

Prove that Python Hosted Agent and Prompt Agent variants, published natively to Microsoft Teams through Microsoft Foundry Agent Service, can reuse the same versioned requester/reviewer MCP contracts and deterministic platform to guide a requester through structured intake, detect gaps and contradictions, route the result through human review, preserve the approved immutable revision as the system of record, and validate handover through a versioned downstream contract — while keeping authorization, validation, persistence, identity, lifecycle, and audit logic outside model control, and while proving the deployment is repeatable (Bicep + `azd`) and privacy/security-shaped (managed identity, Key Vault, private data-service access) from the first milestone.

### POC Success Criteria

| ID | Criterion | Required Evidence | Accountable Owner |
|---|---|---|---|
| POC-01 | A requester completes intake, clarification, confirmation, submission, reviewer feedback, resubmission, approval, and versioned downstream handover in Teams through each enabled agent variant without an administrator changing data manually | Recorded end-to-end tests and demo evidence for Hosted and Prompt variants from a deployed environment | Product |
| POC-02 | Every accepted field update is persisted before success is shown; an interrupted session resumes from the persisted request, including resuming through the other agent variant | Integration, cross-variant resume, and recovery test evidence | Engineering |
| POC-03 | Only an assigned reviewer or authorised administrator can approve or reject through either enabled agent variant; the approved revision is immutable | Authorisation, state-transition, agent-contract, and concurrency test evidence | Security |
| POC-04 | `azd up` provisions and deploys a clean environment from Bicep, including every enabled agent variant and the shared command service, and deployed workloads reach customer-owned data services through the selected private-endpoint topology | Deployment log, Bicep preflight result, per-variant smoke tests, DNS/connectivity evidence | DevOps |


POC criteria and thresholds are frozen before release-candidate evaluation begins. A scope or threshold change creates a new approved baseline and requires a new release candidate and complete evaluation; the failed result remains in the release evidence.


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

### User Story 1.4: Pre-Submission Review and Confirmation

*As a requester, I want to review and confirm the captured requirements so that only correct information is submitted for reviewer approval.*

**Acceptance Criteria**

- Requester reviews and can correct captured requirements before submission.
- Confirmation creates and submits an immutable revision for review.
- If the requester does not confirm, the request remains editable and is not submitted.
- Requester confirmation is distinct from reviewer approval and does not grant approval authority.

**Priority:** Must Have (MVP)

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
- Automated clarification stops when the minimum quality threshold is met or the maximum attempt count is reached.
- The quality threshold is measurable and versioned.
- Maximum clarification attempts and an escalation path are defined; reaching the limit below threshold blocks normal submission until the escalation is resolved.
- Users can review and correct inferred information before proceeding.

**Priority:** Must Have (MVP)

## Epic 3: Approved Structured Output

### User Story 3.1: Access Approved Request

*As a requester, I want the approved request retained as an immutable structured revision so that it can be viewed, audited, and handed over consistently.*

**Acceptance Criteria**

- Approval identifies the exact immutable request revision stored in Cosmos DB.
- Authorised requesters, assigned reviewers, and administrators can view the approved structured revision and its status through the supported Teams experience.
- The approved revision records the agent kind, agent/configuration, model, instructions, Toolbox, MCP contract, template, schema, and policy versions that produced it.
- The approved structured representation is schema-validated and is the source for downstream handover.
- No Word or PDF generation is required for the MVP.
- A request transitions from Approved to Completed when all enabled mandatory handovers succeed.

**Priority:** Must Have (MVP)

## Epic 4: Persistence & Workflow

### User Story 4.1: Save Request

*As a system, I want to persist intake requests so they can be tracked and audited.*

**Acceptance Criteria**

- Store request data.
- Store conversation history.
- Store immutable request revisions, reviews, workflow history, and delivery status.
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


**Priority:** Must Have

## Epic 6: Downstream Automation

### User Story 6.1: Versioned Approved-Request Handover

*As a downstream owner, I want approved requests delivered through a versioned contract so that integrations are reliable and auditable.*

**Acceptance Criteria**

- Only an approved immutable revision can be handed over.
- The payload contract is schema-validated, versioned, and covered by contract tests.
- Delivery uses an approved workload identity and an idempotency key.
- Transient failures are retried without duplicating business effects.
- Permanent or exhausted failures are dead-lettered, visible to operators, and recoverable through an audited replay process.
- Enabled mandatory handovers must succeed before the request transitions to Completed.
- A contract-test stub is available until the first downstream integration is approved.

**Priority:** Must Have (MVP)

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
- Integration tests cover persistence, notifications, and enabled downstream services.
- End-to-end tests cover intake, clarification, review, rejection, resubmission, approval, and recovery flows.
- Contract tests validate structured outputs and enabled APIs.
- Tests run in continuous integration and failures block release.
- The same requester/reviewer MCP contract suite and end-to-end business scenarios run against both agent variants.
- Cross-variant tests start a request with one variant and resume it with the other without losing state or bypassing concurrency controls.

**Priority:** Must Have (MVP Release Gate)

### User Story 8.2: AI Failure and Regression Testing

*As a quality owner, I want AI-specific failure tests so that unsafe or unreliable behavior is detected.*

**Acceptance Criteria**

- Tests cover hallucinated fields, missed and falsely reported gaps, irrelevant or repeated questions, missed contradictions, and unsupported claims.
- Tests cover prompt injection, sensitive-data disclosure, malformed input, excessively long input, and hostile content.
- The agent fails safely when required services, models, or tools are unavailable.
- Non-deterministic scenarios use repeated runs or tolerance ranges defined by the evaluation framework.
- Differential evaluation compares semantic business outcomes across Hosted and Prompt variants without requiring identical prose; each variant must meet release thresholds independently.
- Critical regressions block release.

**Priority:** Must Have (MVP Release Gate)

### User Story 8.3: Non-functional and Accessibility Testing

*As a release owner, I want non-functional tests so that the product is usable and reliable under expected conditions.*

**Acceptance Criteria**

- Performance tests verify agreed response-time, throughput, concurrency, and request-payload-size targets.
- Resilience tests verify timeout, retry, idempotency, duplicate prevention, and recovery behavior.
- Security tests verify authentication, authorisation, data isolation, and common prompt and application attack paths.
- Accessibility tests verify the target defined in Epic 11.
- Test evidence is attached to the release record.

**Priority:** Must Have (MVP Release Gate)

### User Story 8.4: Deterministic Package and Dependency Boundaries

*As an architecture owner, I want enforceable package boundaries so that model-facing code cannot bypass deterministic authorization, validation, persistence, or identity controls.*

**Acceptance Criteria**

- The repository produces versioned `intake-agent-contracts` and shared behavior specifications for both agent variants, plus private `intake-application` and `intake-domain` Python packages consumed by the Intake Command Service and all state-changing workers.
- CI import-boundary contracts fail when channel/orchestration code imports persistence modules, repositories, Azure SDK clients, credential providers, or mutable identity implementations.
- The domain layer contains no Foundry-specific types and depends only on the Python standard library and approved domain-only dependencies.
- Agent-facing contracts contain no Foundry run/thread objects, prompt text, Teams card payloads, or channel-specific business state.
- The deterministic packages are built once per release; the Intake Command Service and every state-changing worker are promoted with the same approved version unless an explicitly tested compatibility window applies.
- Hosted and Prompt variants can be versioned and rolled back independently only against MCP contract versions proven compatible in CI.
- Release evidence records the package version for every deployed component and fails promotion when versions are incompatible.

**Priority:** Must Have (MVP Release Gate)

## Epic 9: Security, Privacy & Governance

### User Story 9.1: Identity and Access Control

*As a data owner, I want controlled access so that request information is only available to authorised users and services.*

**Acceptance Criteria**

- Authentication is required for requester, reviewer, administrator, and service access.
- A role-permission matrix covers viewing, editing, reviewing, approving, exporting, deleting, and administering requests.
- Access is denied by default and enforced at the request and immutable-revision level.
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
- Deletion covers primary data, immutable revisions, conversation history, delivery records, and applicable backups according to policy.

**Priority:** Must Have (MVP Release Gate)

### User Story 9.3: AI and Configuration Governance

*As a governance owner, I want controlled AI configuration changes so that behavior is traceable and reversible.*

**Acceptance Criteria**

- Agent kind, agent/configuration, model, instructions, Toolbox, MCP contract, template, schema, policy, and evaluation-dataset versions are recorded for every approved structured output and evaluation result.
- Configuration changes require review, test evidence, and an audit record.
- System instructions and trusted context are isolated from untrusted user content.
- Prompt-injection attempts cannot override access controls or disclose protected information.
- An approved version can be restored without data loss.

**Priority:** Must Have (MVP Release Gate)

### User Story 9.4: Private Networking for Data Services

*As a security owner, I want customer-owned data services reachable only through private connectivity so that the platform is not exposed to the public internet.*

**Acceptance Criteria**

- Every data-bearing service (Cosmos DB, Blob Storage, Azure AI Search, Service Bus, Key Vault) has a defined VNet/subnet and private endpoint design.
- Private DNS zones are configured so service names resolve to private IPs from every deployed consumer that requires data-plane access, including the Intake Command Service, Functions workers, evaluation job, and each enabled agent variant's approved Search/MCP access where applicable.
- Public network access is disabled on each service where the platform supports it, unless an approved exception exists.
- A developer-access decision (VPN, jumpbox, dev tunnel, or cloud-only) is documented for local development and CI/CD.
- Both the baseline and hardened deployment variants are represented in Bicep until the production topology is confirmed (Epic 12).
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

### User Story 10.2: Reliability and Recovery

*As an operator, I want state changes and asynchronous work to recover safely so that failures do not lose or duplicate business effects.*

**Acceptance Criteria**

- Mutating commands are idempotent and use optimistic concurrency.
- State changes, audit events, and outbox records are committed atomically within the request partition.
- Queue consumers implement bounded retries, duplicate prevention, dead-letter handling, and audited replay.
- Recovery-point and recovery-time objectives are defined and tested.
- Backup and restoration tests verify request, revision, review, audit, and delivery integrity.

**Priority:** Must Have (MVP Release Gate)

### User Story 10.3: Safe Deployment and Rollback

*As a release owner, I want controlled deployments so that faulty changes can be limited and reversed.*

**Acceptance Criteria**

- Development, test, and production environments have controlled promotion.
- Continuous integration enforces automated tests, evaluation thresholds, and security checks.
- Risky model, prompt, template, and workflow changes support staged rollout or feature flags.
- Hosted Agent, Prompt Agent, shared behavior, Toolbox, and MCP contract versions are pinned and independently rollback-compatible.
- Rollback procedures cover application and AI configuration versions.
- Operational runbooks define incident ownership, diagnosis, recovery, and communication.

**Priority:** Must Have (MVP Release Gate)

## Epic 11: Experience and Accessibility

### User Story 11.1: Accessible Teams Experience

*As a requester or reviewer, I want a clear and accessible Teams experience so that I can complete required actions without avoidable barriers.*

**Acceptance Criteria**

- Intake, clarification, confirmation, review, feedback, approval, rejection, status, and resume flows work through supported Teams interactions.
- User-facing validation, authorization, conflict, and service errors identify the problem and an actionable next step without exposing sensitive details.
- Interactive controls, approved request summaries, and supported Teams flows meet WCAG 2.2 AA requirements within documented platform constraints.
- Keyboard navigation, screen-reader behavior, focus order, labels, contrast, and text scaling are tested for required flows.
- Adaptive Cards, attachments, deep links, proactive notifications, and accessibility behavior are validated in an early platform spike.
- Any unsupported native Teams behavior that blocks a required flow triggers an explicit architecture and scope decision.
- Both enabled agent variants meet the same business capability and accessibility criteria; variant-specific wording and interaction details may differ.

**Priority:** Must Have (MVP Release Gate)

## Epic 12: Azure Infrastructure and Deployment

### User Story 12.1: Bicep Infrastructure Modules

*As a DevOps engineer, I want Azure resources defined in Bicep so that environments are repeatable and reviewable.*

**Acceptance Criteria**

- An `infra/` folder contains Bicep modules for the Foundry project, Hosted Agent hosting, Prompt Agent configuration where supported by the provisioner, Azure Bot Service resource/association where supported, the existing or dedicated Container Apps environment and private Intake Command Service required by ADR-015 through ADR-017, Cosmos DB, Blob Storage, Azure AI Search, Service Bus, Azure Functions, the private Container Apps evaluation job, evaluation evidence storage, Key Vault, monitoring, networking, workload identities, and the dedicated notification Entra application.
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

- `azure.yaml` at the repository root maps every source-deployed component to its Azure host, including the Hosted Agent, Prompt Agent configuration deployment hook where applicable, private Intake Command Service, Functions workers, and Container Apps evaluation job; the component/provisioner matrix records resources handled by Foundry publishing or Microsoft 365 administration instead.
- `azd provision`, `azd deploy`, and `azd up` succeed end-to-end against a clean environment.
- Required `azd env` values are documented; no secrets are committed to `azd` environment files.
- Managed identity is used for Azure resource access; secrets that cannot use managed identity are stored in Key Vault.
- CI/CD (GitHub Actions with workload identity federation) provisions and deploys test and production environments per `architecture-design.md` §18 and §20 (Slice 1).

**Owner:** DevOps

**Priority:** Must Have (MVP Release Gate)

### User Story 12.3: Environment and Region Selection

*As an architecture owner, I want environment and region decisions recorded so infrastructure choices are traceable.*

**Acceptance Criteria**

- Target Azure region is selected after checking Hosted Agent, Prompt Agent, Toolbox/MCP, private networking, data-residency, and quota support, preferring the region with the broadest required service availability.
- Baseline (public Foundry access with private customer data services) and hardened (private Foundry and private customer data services) deployment variants are both representable from the same Bicep modules until compliance selects one (`architecture-design.md` ADR-008).
- Dev, test, and production environments have distinct parameter sets and controlled promotion.
- Region and environment decisions are recorded as architecture decisions (see Architecture Decisions section).

**Owner:** Architecture

**Priority:** High

### User Story 12.4: Local Development Profile

*As a developer, I want to run the intake workflow locally with lightweight service substitutes so that I can develop and test without provisioning Azure resources.*

**Acceptance Criteria**

- A documented local command starts the application without requiring Azure credentials or provisioned cloud resources.
- The local profile provides in-memory implementations for conversation history, request persistence, delivery status, messaging, and other required external service contracts.
- Local substitutes implement the same domain interfaces as Azure-backed adapters so application and domain behavior is unchanged when configuration selects a different backend.
- Developers can seed representative templates and identities and reset all local state deterministically.
- Local state is clearly identified as ephemeral, is excluded from production configurations, and is never accepted as deployment, durability, security, or release-gate evidence.
- Automated tests exercise the local profile, including multi-turn conversation history, request resume within the running process, and clean reset behavior.
- Agent contract tests can run against the local profile without importing either Foundry runtime implementation into the deterministic application/domain layers.
- Setup documentation identifies features that require Azure or Teams and explains how to switch from local substitutes to deployed integrations.

**Owner:** Engineering

**Priority:** Must Have (MVP)

## Epic 13: POC Demo Script and Guide

### User Story 13.1: End-to-End Demo Script

*As a presenter, I want a step-by-step demo script so that I can reliably demonstrate the intake workflow on demand.*

**Acceptance Criteria**

- Script drives the primary Teams workflow: intake, clarification, submission, review, feedback, approval, and handover through the versioned downstream contract to the selected integration or contract-test stub.
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
- Post-deploy smoke tests confirm the Teams workflow for each enabled Hosted/Prompt variant, the shared Intake Command Service, and background workers are live.
- Private connectivity to Cosmos DB, Storage, Search, Service Bus, and Key Vault is validated from the deployed host, not a developer machine, for the hardened variant.
- Release evidence identifies every enabled agent kind, agent/configuration version, instructions version, Toolbox version, MCP contract version, and deterministic package version.

**Owner:** DevOps


**Priority:** Must Have (MVP Release Gate)

## Epic 15: Documentation of Architecture Decisions, Workflow Diagrams, and Operational Runbooks

### User Story 15.1: Architecture Decision Records

*As an engineering lead, I want architecture decisions documented and kept current so that the next team can build on this POC.*

**Acceptance Criteria**

- Architecture decisions and their recorded status (Accepted/Proposed) are kept current in `architecture-design.md` §21 as decisions are confirmed.
- Open decisions and validation spikes (`architecture-design.md` §23) are tracked to closure with an owner and target date.
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
| Production network topology | Baseline vs. hardened — pending security/compliance confirmation | Open — `architecture-design.md` §23 item 1 |
| Model and Azure region | Pending Hosted Agent, Prompt Agent, Toolbox/MCP, networking, data-residency, and quota check | Open — `architecture-design.md` §23 item 2 |
| Agent variants | Hosted and Prompt Agents are parallel adapters over shared requester/reviewer MCP contracts; both pass independent release gates | Accepted — ADR-016 and ADR-017 |
| Reviewer command surface | Separate reviewer Toolbox/MCP contract and delegated scope on the shared Intake Command Service | Accepted — ADR-016 |

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
- Every enabled agent variant passes the same business-capability, contract, security, accessibility, and evaluation gates independently.
- Cross-variant resume proves that persisted product state, not agent conversation memory, is authoritative.
- Database and data-service networking uses the private endpoint/private DNS design, with public access disabled where supported.
- A clean-environment deployment is verified and each POC success criterion is checked against the deployed system (Epic 14).
- A demo script and an operational runbook are documented, with architecture decisions and workflow diagrams committed (Epics 13 and 15).
- User-facing and operational documentation is current.
- Evidence is linked to the release record and approved by the accountable owner.
