# Intake Agent MVP Demo Guide

**Status:** Script skeleton; validate against a deployed environment before presentation.

## Prerequisites

- Dedicated demo environment provisioned through the same Bicep/`azd` contract.
- Designated requester, assigned reviewer, and operator identities.
- Approved seed template, downstream contract-test stub, Hosted Agent, and Prompt Agent versions.
- Clean telemetry view and correlation-ID lookup.
- Reset procedure approved by the data owner; do not use production data.

## Script

1. As requester in Hosted Agent, start an incomplete request and show deterministic missing fields.
2. Add values, introduce a contradiction, and show focused clarification without invented resolution.
3. Interrupt the session; resume the same request through Prompt Agent and show persisted fields/provenance.
4. Review and correct the summary, confirm the immutable revision, and submit it.
5. As an unassigned reviewer, demonstrate authorization denial.
6. As the assigned reviewer, request changes with rationale.
7. As requester, revise, reconfirm, and resubmit.
8. As assigned reviewer, approve the exact immutable revision.
9. Show versioned, idempotent handover to the contract-test stub and transition to Completed.
10. Show correlated audit/telemetry without sensitive request content.
11. Show the signed scorecard with both per-variant and differential release results.

For each step capture the request ID, expected lifecycle state, allowed actions, visible wording/Teams artifact, persisted revision, and evidence link. Stop the demo if identity, state, or expected output differs; do not repair data manually.

## Reset

Use the runtime-owned demo reset command after confirming the environment name and fixture scope. The command must delete only designated synthetic requests, reset the contract stub idempotently, preserve required audit evidence, and report a verification summary. This command is an integration dependency.
