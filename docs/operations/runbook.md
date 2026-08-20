# Intake Agent Operations Runbook

**Status:** Operational skeleton. Resource-specific commands, owners, alert links, retention values, and recovery approvals must be completed and exercised before production.

## Common controls

- Use an approved operator identity, change/incident record, environment, candidate SHA, and correlation ID.
- Never paste request content, tokens, secrets, or dead-letter bodies into tickets or terminals.
- Capture start/end time, operator, command/output references, affected versions, validation, and approvals.
- Stop if identity, scope, backup point, immutable version, or expected outcome is unclear.

## Deploy or redeploy

1. Confirm CI `Required checks`, dataset/threshold approval, change approval, capacity/quota, rollback target, and maintenance communication.
2. Trigger `.github/workflows/release.yml` with an immutable SHA already on `main`, approved environment, and deployment variant.
3. The test Environment runs `azd up --no-prompt`; do not reproduce deployment with ad hoc `az`, ARM, or portal changes.
4. Require per-variant smoke, contract, cross-variant resume, private connectivity, telemetry, automated evaluation, human review, and signed evidence.
5. For production, approve the separate production Environment only after the test evidence passes; production promotion then uses the same commit and `azd` contract.
6. Pin the approved versions. Do not select “latest”.

## Rollback

1. Declare the rollback, freeze promotion, and identify the last signed compatible evidence manifest.
2. Check data/schema backward compatibility and pin the compatible Hosted Agent, Prompt Agent, shared behavior, Toolbox, MCP contract, command service, and worker versions.
3. Redeploy the approved prior commit through the same `azd` release workflow. Do not roll back authoritative data unless the incident commander also invokes restore.
4. Run smoke, authorization, cross-variant resume, queue health, and telemetry checks.
5. Record which version caused the rollback and preserve failed evidence.

## Secret or certificate rotation

1. Inventory the exceptional Key Vault secret/certificate, consumers, expiry, owner, and rotation overlap. Managed identity remains the default.
2. Create the replacement in Key Vault; never place values in GitHub, source, Bicep parameters, logs, or `azd` environment files.
3. Grant only required identities, update version references through the governed deployment/configuration path, and redeploy through `azd`.
4. Verify every consumer before disabling the old version; monitor authentication failures.
5. Revoke/delete the old version after the approved overlap and capture Key Vault audit evidence.

## Dead-letter replay

1. Pause the affected consumer or replay path and capture queue/subscription, message count, failure class, and correlation IDs without message bodies.
2. Fix the root cause and prove the handler is idempotent against a safe sample.
3. Obtain replay approval; quarantine poison, expired, unauthorized, or schema-incompatible messages.
4. Use the runtime-owned audited replay command with a bounded batch and dry-run mode. The command is an integration dependency.
5. Confirm original message ID/idempotency key, new delivery result, no duplicate business effect, and declining DLQ count.

## Restore

1. Incident commander and data owner choose a restore point within the approved RPO/RTO and place writes in the documented safe mode.
2. Restore Cosmos DB/Storage using the infrastructure-owned procedure into an isolated target first.
3. Validate request aggregates, immutable revisions, reviews, audit/outbox ordering, delivery status, search rebuild requirements, and evidence integrity.
4. Reconcile events and downstream effects idempotently before traffic resumes.
5. Record measured RPO/RTO and do not treat an untested provider backup as restore evidence.

## Data deletion

1. Validate requester/data-owner authority, legal hold, scope, retention policy, and request/revision identifiers.
2. Execute the retention-worker deletion workflow across primary data, immutable revisions where policy permits, conversation state, delivery records, Search, telemetry, DLQs, evaluation exports, and applicable backups.
3. Record completion per store without retaining deleted content.
4. If Foundry conversation deletion/expiry cannot be executed and evidenced, escalate and block production use rather than claiming deletion.

## Incident response

1. Triage severity, incident commander, security/privacy involvement, blast radius, variants, tenant, versions, and correlation IDs.
2. Contain with the narrowest reversible control: disable a variant, stop evaluation/promotion, pause workers, or roll back. Preserve authoritative state and evidence.
3. Investigate correlated Teams/Foundry/command/worker/queue/evaluation telemetry with redaction.
4. Recover using rollback, DLQ replay, restore, or deletion procedures; communicate on the approved cadence.
5. Require post-recovery smoke and evidence, document timeline/root cause/actions, and feed only reviewed/redacted examples into dataset curation.

## Teardown

1. Obtain owner, data-retention, legal-hold, evidence-export, and shared-resource approvals.
2. Export required signed release/audit evidence and verify its retention location and digest.
3. Disable Teams catalog exposure and agent endpoints, drain or quarantine queues, stop workers/jobs, and complete required deletion.
4. Run `azd down --purge --force` only for the selected disposable environment and only after reviewing the resolved subscription/environment/resource group.
5. Separately remove resources owned by Microsoft 365 administration or Foundry publishing only through their documented owner path.
6. Verify resource removal, private DNS/RBAC/federated credential cleanup, budget/alert cleanup, and absence of orphaned data.

## Production blockers

Final region/network topology, retention/legal hold, Foundry deletion semantics, replay tooling, restore commands, runtime smoke script, alert ownership, signing/canonicalization, resource names, and environment-specific RPO/RTO evidence remain to be integrated and tested.
