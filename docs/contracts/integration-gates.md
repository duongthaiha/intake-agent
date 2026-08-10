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

```
PR → lint + type-check + unit + component + contract → merge
main → integration tests + local demo verification → deploy to dev
release → evaluation job + acceptance gates → promote to test/prod
```

## Quality thresholds

| Metric | Threshold | Enforcement |
|--------|-----------|-------------|
| Unit test coverage (`intake_domain`) | ≥ 80% | CI fail |
| Type check | Zero errors | CI fail |
| Import boundary | Zero violations | CI fail |
| Lint (ruff) | Zero errors | CI fail |
| Component test pass rate | 100% | CI fail |
| Contract test pass rate | 100% | CI fail |
| Security scan (bandit + safety) | Zero high/critical | CI fail |
