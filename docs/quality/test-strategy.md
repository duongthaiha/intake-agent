# Test Strategy — intake-agent

**Owner:** Switch (Quality Engineer)  
**Version:** 0.3  
**Date:** 2026-08-07  
**Status:** Active — Integration follow-up complete

---

## 1. Overview

This document defines the quality strategy for the intake-agent POC. It maps each POC success criterion to a concrete test layer, documents gate requirements, and records expected interface mismatches for integration follow-up.

---

## 2. Test Pyramid

```
                        ┌──────────────┐
                        │     E2E      │  (post-deployment; Teams + Foundry required)
                      ┌─┴──────────────┴─┐
                      │   Integration    │  (LocalAdapter; no Azure)
                    ┌─┴──────────────────┴─┐
                    │   Component          │  (command handlers + in-memory repos)
                  ┌─┴────────────────────────┴─┐
                  │    Contract              │  (schema/protocol validation)
                ┌─┴──────────────────────────────┴─┐
                │         Unit                   │  (domain entities, state machine, authz)
                └────────────────────────────────────┘
```

| Layer | Location | Runs without Azure | Gate |
|-------|----------|-------------------|------|
| Unit | `tests/unit/` | ✅ | PR merge |
| Contract | `tests/contract/` | ✅ | PR merge |
| Component | `tests/component/` | ✅ | PR merge |
| Security | `tests/security/` | ✅ | PR merge |
| Accessibility | `tests/teams/` | ✅ | PR merge |
| Integration | `tests/integration/` | ✅ (in-memory) | Merge to main |
| Evaluation | `evaluation/` | ✅ (dataset + scorecard) | Release gate |
| E2E | `tests/e2e/` | ❌ (requires Teams/Foundry) | Release candidate |
| Azure | marked `@azure` | ❌ (requires credentials) | Set `INTAKE_RUN_AZURE_TESTS=1` |

---

## 3. POC Coverage Map

| POC Criterion | Test File | Status |
|---|---|---|
| POC-01 End-to-end Teams flow | `tests/e2e/` | Pending deployment |
| POC-02 Session resume | `tests/component/test_request_lifecycle.py::test_resume_from_persisted_request` | Ready |
| POC-03 Reviewer-only approval + immutable revision | `tests/unit/test_authorization_matrix.py`, `tests/component/test_request_lifecycle.py` | Ready |
| POC-04 Artifacts from immutable revision | `tests/contract/test_command_schemas.py` (event shapes) | Partial — awaits artifact worker |
| POC-05 Idempotent delivery | `tests/component/test_idempotency.py` | Ready |
| POC-06 Import boundary | `tests/unit/test_infrastructure_static.py::test_reference_domain_has_no_infra_dependencies` | Ready |
| POC-07 azd deploy | Infrastructure team (Tank) — not Switch's scope | N/A |
| POC-08 Evaluation scorecard | `evaluation/test_scorecard.py` | Ready |

---

## 4. Quality Gates

### PR Merge Gate

```
pytest -m "unit or contract or component or security or accessibility"
```

Requirements:
- 100% pass rate
- Coverage ≥ 80% on `intake_domain` (when implementation arrives)
- Zero import-linter violations
- Zero ruff/mypy errors

### Merge to Main Gate

```
pytest -m "unit or contract or component or security or accessibility or integration"
```

### Release Gate (POC-08)

```
pytest -m evaluation
python -m evaluation.scorecard evaluation/dataset/cases.jsonl results/eval_run.jsonl
```

Requirements:
- capture_accuracy ≥ 0.85
- gap_recall ≥ 0.90
- gap_precision ≥ 0.80
- unsupported_claim_rate ≤ 0.05
- injection_safe_rate = 1.00

---

## 5. Running Tests

### Full local suite

```bash
pip install -e '.[dev]'
pytest tests/ evaluation/test_scorecard.py -q
pytest tests/ evaluation/test_scorecard.py --cov=src/intake_domain --cov-report=term-missing -q
```

**Current baseline (2026-08-07, integration follow-up complete):**

| Metric | Value |
|--------|-------|
| Total tests | **573 passed, 0 failed** |
| `intake_domain` coverage | **92.88%** ✅ (gate: 80%) |
| Test wall time | ~3.5 s |

### Azure integration tests

```bash
export INTAKE_RUN_AZURE_TESTS=1
pytest -m azure -v
```

---

## 6. Interface Mismatches and Known Gaps

### Resolved mismatches (integration follow-up complete)

| # | ADR spec | Trinity/Neo delivery | Resolution |
|---|----------|---------------------|------------|
| 1 | `LocalAdapter.handle_message(message, user_id)` | Individual command methods (`get_or_create_request`, `propose_updates`, `submit_for_review`, `record_review_decision`) | Accepted — command-per-method is cleaner. Tests updated to real API. |
| 2 | `get_or_create_request()` → `revision` key | Returns `current_revision` | Tests fixed to use `current_revision`. |
| 3 | `IdempotencyStore.check()` returns raw `Any` | Returns `StoredResult \| None` with `.result` attribute | Tests fixed; handlers use `stored.result`. |

### Open action items (owner: Trinity)

- **`LocalAdapter.record_review_decision()` assigns hardcoded `roles=frozenset(["reviewer"])`** — production Foundry adapter MUST construct `ActorContext` from verified Entra token claims, not hardcoded roles. HTTP 403 enforcement for non-reviewers is blocked until this is fixed. Documented in `test_document_review_actor_enforcement`.

---

## 7. Evaluation Dataset

Location: `evaluation/dataset/cases.jsonl`

12 cases covering:
- Single and multi-field capture
- Progressive multi-turn capture
- Contradiction detection
- Low-confidence flagging
- Injection safety
- Session resume (POC-02)
- Unsupported claim detection (hallucination guard)
- Full end-to-end flow to review-ready

---

## 8. Security Test Coverage

| Case | Test |
|------|------|
| Unauthenticated actor denied all commands | `test_security_cases.py::test_empty_roles_denied_all_commands` |
| Unknown role not implicitly privileged | `test_security_cases.py::test_unknown_role_is_not_implicitly_privileged` |
| SQL injection stored verbatim | `test_security_cases.py::test_injection_payload_stored_as_data_not_executed` |
| XSS stored verbatim | `test_security_cases.py::test_injection_payload_stored_as_data_not_executed` |
| Template injection stored verbatim | `test_security_cases.py::test_injection_payload_stored_as_data_not_executed` |
| PII not logged in errors | `test_security_cases.py::test_actor_context_does_not_log_tenant_id_verbatim` |
| No Azure SDK in domain | `test_security_cases.py::test_domain_package_does_not_import_azure_sdk` |
| Actor context is frozenset, not list | `test_security_cases.py::test_model_cannot_supply_roles` |

---

## 9. Decisions

- Reference domain (`tests/fixtures/reference_domain.py`) is the authoritative shape of domain interfaces until Trinity delivers `src/intake_domain`.
- Evaluation thresholds are frozen in `evaluation/scorecard.py::THRESHOLDS`.
- A threshold change requires a new approved baseline (POC-08).
- Azure integration tests are guarded by `INTAKE_RUN_AZURE_TESTS=1` environment variable.
- `tests/**` and `evaluation/**` are Switch's exclusive ownership per ADR-012.
