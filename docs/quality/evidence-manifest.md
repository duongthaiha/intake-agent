# Signed Evidence Manifest

The JSON Schema is `evaluation/schemas/evidence-manifest.schema.json`. Paths are relative to the manifest directory and cannot escape it. Every artifact carries a SHA-256 digest.

The evaluation service must canonicalize the manifest with the `signature.value` omitted, sign those bytes with an approved managed-identity-accessed key, then add the signature block. The verification service must repeat canonicalization and validate the signature against the pinned key ID and certificate thumbprint. Signing keys, algorithms, canonicalization rules, and rotation policy are production decisions; no private key or credential belongs in GitHub.

Local validation:

```text
python scripts/evaluation/verify_evidence.py release-evidence/manifest.json \
  --expected-commit-sha <40-character-sha> \
  --expected-deployment-variant <baseline-or-hardened> \
  --expected-run-id <run-id> \
  --expected-dataset-version 1.0.0 \
  --expected-threshold-set-version 1.0.0
```

This command validates required fields, passing decision, both variants, approvals, artifact containment, and digests. It does not replace server-side cryptographic verification.
