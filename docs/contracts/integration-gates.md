# Integration and Acceptance Gates

## Slice 2 (Vertical Path) — Definition of Done

### Unit gate (PR merge requirement)

- [ ] All domain entity tests pass (`tests/unit/`)
- [ ] Import-linter contracts pass (no cross-boundary imports)
- [ ] Type checking passes (`mypy --strict` on `intake_domain`)
- [ ] Code coverage ≥ 80% on `intake_domain`
- [ ] Ruff lint passes (zero warnings)

### Component gate (PR merge requirement)

- [ ] Command handler tests pass with in-memory repositories (`tests/component/`)
- [ ] Optimistic concurrency conflict scenario tested
- [ ] Idempotent command replay tested
- [ ] State machine transition tests cover all valid + invalid paths
- [ ] Authorization matrix tests cover requester/reviewer/admin roles

### Contract gate (PR merge requirement)

- [ ] Command schemas validate against `docs/contracts/command-event-schemas.md`
- [ ] Event envelope structure matches contract
- [ ] Error response structure matches contract
- [ ] Pydantic models serialise/deserialise round-trip correctly

### Integration gate (merge to main)

- [ ] `LocalAdapter` demonstrates full vertical flow:
  - Create request → capture fields → validate → persist → resume → submit → review-ready
- [ ] In-memory persistence behaves identically to contract (ETag, conditional create)
- [ ] Outbox items are created in the same transaction as state changes

### Acceptance gate (slice sign-off)

- [ ] POC-02 evidence: interrupted session resumes from persisted request (in-memory backend)
- [ ] POC-06 evidence: import-linter CI results showing boundary enforcement
- [ ] Local demo script runs end-to-end without Azure credentials

## Slice 2 → Slice 3 promotion criteria

- All Slice 2 gates pass.
- Cosmos DB adapter integration test passes against real Cosmos (emulator acceptable for CI).
- Teams spike findings documented (even if spike is blocked).

## CI pipeline structure

`.github/workflows/ci.yml` implements this as a set of blocking jobs
aggregated into one required status check (`Required Checks` /
`required-checks`); see `docs/quality/test-strategy.md §4` for the full
gate-to-job mapping.

```
PR → bicep-validate, lint-and-types (ruff+mypy), import-boundaries,
     pr-tests (unit/contract/component/security/accessibility + coverage),
     bandit-scan (HIGH severity), secret-scan, iac-scan (HIGH/CRITICAL)
     → Required Checks → merge
main push → adds integration-tests (in-memory, no Azure creds) → deploy to dev
release → evaluation job (eval.yaml, evaluation/) + acceptance gates,
          run separately from ci.yml → promote to test/prod
```

Live Azure durability tests (`tests/azure`, `-m azure`) and the evaluation
gate stay out of `ci.yml` by design — they require an approved
VNet-connected runner and/or Foundry credentials.

## Quality thresholds

| Metric | Threshold | Enforcement |
|--------|-----------|-------------|
| Unit test coverage (`intake_domain`) | ≥ 80% | CI fail (`.coveragerc`, job `pr-tests`) |
| Type check | Zero errors | CI fail (`mypy --strict`, job `lint-and-types`) |
| Import boundary | Zero violations | CI fail (`lint-imports`, job `import-boundaries`) |
| Lint (ruff) | Zero errors | CI fail (job `lint-and-types`) |
| Component test pass rate | 100% | CI fail (job `pr-tests`) |
| Contract test pass rate | 100% | CI fail (job `pr-tests`) |
| Security scan (Bandit HIGH severity) | Zero | CI fail (`bandit -r src/ -lll`, job `bandit-scan`) |
| Secret scan (Trivy) | Zero detections | CI fail (job `secret-scan`) |
| IaC scan (Trivy, HIGH/CRITICAL) | Zero | CI fail after Bicep-to-ARM compilation (job `iac-scan`) |
| Bicep build + lint | Zero errors | CI fail (job `bicep-validate`) |
