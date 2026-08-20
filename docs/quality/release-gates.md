# Release Gates

## Frozen inputs

Before a release candidate starts, accountable owners approve:

- Dataset manifest and exact dataset version.
- Threshold configuration and threshold-set version.
- Hosted Agent, Prompt Agent, model, instructions, shared behavior, Toolbox, MCP contract, policy, template, schema, and deterministic package versions.
- Human sample selection and reviewer assignments.

The committed `v1.0.0` dataset and thresholds are deliberately marked pending approval. This is a **blocking integration dependency**, not a default approval. Editing thresholds or cases after a failed run requires a new reviewed version and a complete new evaluation; failed evidence is retained.

## Automated decision

`evaluation.scorecard.build_scorecard` returns `pass` only when:

1. The evaluation run status is `succeeded`.
2. Dataset and threshold baselines are approved.
3. Every dataset case has one unique result for each variant.
4. Every required per-variant metric exists and passes.
5. Every differential metric exists and passes.
6. No critical failure is observed.

Timeout, cancellation, unknown status, duplicate result, malformed input, missing result, missing metric, incomplete variant coverage, non-passing human review, unsigned evidence, missing artifact, or digest mismatch fails closed.

## Required release evidence

The manifest schema is `evaluation/schemas/evidence-manifest.schema.json`. The manifest binds the candidate commit and deployment variant to:

- Component/configuration versions and immutable package/container digests.
- Dataset and threshold versions.
- Per-variant and differential scorecards.
- Human-review decisions.
- Test, security, accessibility, deployment, smoke, connectivity, rollback, and runbook evidence.
- Artifact SHA-256 digests.
- Release approvals.
- A managed-identity-backed `RS256` or `ES256` signature.

`verify_evidence.py` validates required structure and local artifact digests. Cryptographic signature verification against the approved key/certificate must be implemented by the evaluation/evidence service before production; a merely populated signature object is not sufficient production proof.

## Integration dependencies

- Runtime result adapter that emits the documented result shape for both variants.
- Approved evaluation API audience and private status endpoint.
- Evaluation job managed identity and evidence-store write permissions.
- Managed signing key/certificate and server-side signature verification path.
- Runtime-owned post-deploy smoke/E2E/cross-variant script.
- Final Bicep/`azure.yaml`, environment variables, private runner, GitHub Environment approvals, and retention policy.
- Domain, quality, security, and release-owner approval of version `1.0.0`.
