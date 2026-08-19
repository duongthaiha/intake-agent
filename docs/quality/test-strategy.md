# Test Strategy — intake-agent

**Owner:** Switch (Quality Engineer)  
**Version:** 0.4
**Date:** 2026-08-19
**Status:** Active — CI hardened to blocking gates only (no continue-on-error, no skip-on-missing)

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

All PR and main-push gates below are enforced by `.github/workflows/ci.yml`
and aggregated into a single required status check, **`Required Checks`**
(job id `required-checks`). Branch protection for `main` should require only
this one check — it fails whenever any dependency job fails, errors, or is
cancelled, and treats a dependency's `skipped` result as failing unless that
job is intentionally exempt (currently only `integration-tests`, which is
scoped to `push` on `main`).

### PR Merge Gate (blocks every PR into `main`)

| Gate | Job | Command |
|------|-----|---------|
| Bicep build + lint | `bicep-validate` | `az bicep build` / `az bicep lint` |
| Ruff | `lint-and-types` | `ruff check src/ tests/ evaluation/` |
| Mypy (strict, `pyproject.toml`) | `lint-and-types` | `mypy src/` |
| Import boundaries | `import-boundaries` | `lint-imports` |
| Documented PR test set + coverage | `pr-tests` | see below |
| Bandit (HIGH severity only) | `bandit-scan` | `bandit -r src/ -lll` |
| Trivy secret scan | `secret-scan` | any detection fails |
| Trivy IaC scan (HIGH/CRITICAL) | `iac-scan` | compile Bicep to ARM JSON, then scan `.trivy-iac/` |

```
coverage run -m pytest -m "unit or contract or component or security or accessibility"
coverage report -m
```

Requirements:
- 100% pass rate on the marker set above
- Coverage ≥ 80% on `intake_domain` — enforced by `.coveragerc`
  (`fail_under = 80`, `source = src/intake_domain`), the single
  authoritative coverage config. `pyproject.toml` intentionally does not
  declare a `[tool.coverage]` table (see the note in that file).
- Zero import-linter violations
- Zero ruff/mypy errors
- Zero HIGH-severity Bandit findings; zero secrets detected; zero
  HIGH/CRITICAL Trivy findings in the ARM JSON compiled from all Bicep files

### Merge to Main Gate (adds, on `push` to `main` only)

| Gate | Job | Command |
|------|-----|---------|
| In-memory integration suite | `integration-tests` | `pytest -m "integration and not azure"` |

This job is intentionally skipped on PRs (not required there); the
`azure`-marked test in `tests/azure/` is excluded here because it requires
an approved VNet-connected runner and is out of scope for this
credential-free pipeline (see "Release Gate" below).

### Release Gate (POC-08) — NOT part of `ci.yml`

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

### Private-network Azure durability gate — NOT part of `ci.yml`

```
export INTAKE_RUN_AZURE_TESTS=1
export INTAKE_AGENT_ENDPOINT=<approved deployed version URL>
pytest -m azure -v
```

Must be run on the approved VNet-connected runner. Confirm the run reports
`0 skipped` — a skip here means the runner lacked `azd`/the endpoint and
proves nothing, it does not substitute for a passing run.

---

## 5. Running Tests

### Full local suite

```bash
pip install -e '.[dev]'
pytest tests/ evaluation/test_scorecard.py -q
coverage run -m pytest -m "unit or contract or component or security or accessibility" -q
coverage report -m
```

Note: `pytest-cov` is not a project dependency, so `pytest --cov=...` is not
a valid local command — use the standalone `coverage` CLI shown above (it
already reads `.coveragerc` automatically), matching what `ci.yml` runs.

**Requires Python 3.11** (per `pyproject.toml`'s `requires-python` and the
version CI pins). On newer local interpreters (3.12+), `pytest.ini`'s
`filterwarnings = error` turns Python's own `asyncio.iscoroutinefunction`
deprecation warning (introduced in 3.12, slated for removal in 3.16) into
hard test failures in a handful of tests that call into
`agent-framework-foundry-hosting`/`azure-ai-agentserver` internals. This is
an interpreter-version artifact, not a product regression — it does not
occur under the Python 3.11 CI runners.

**Current baseline (2026-08-19, CI hardening cycle):** measured on Python
3.14 locally; CI runs on Python 3.11 where the artifact above does not
occur.

| Metric | Value |
|--------|-------|
| PR-gate marker set (`unit or contract or component or security or accessibility`) | 612 passed, 7 failed* |
| Full suite (`tests/ evaluation/test_scorecard.py`) | 768 passed, 8 failed*, 1 skipped (azure, expected) |
| `intake_domain` coverage | **85%** ✅ (gate: 80%) |
| Import-linter | 4 contracts kept, 0 broken |
| Ruff / mypy (strict) | 0 issues |
| Bandit (`-lll`, HIGH only) | 0 findings (7 informational LOW findings, all `assert` usage in `intake_teams/demo/`) |

\* All failures are the Python 3.14 `asyncio.iscoroutinefunction` deprecation
artifact described above; expected to pass under the CI-pinned Python 3.11.

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
| CI has no continue-on-error / skip-on-missing / floating Action refs | `tests/unit/test_cicd_static.py` |
| Bandit HIGH-severity, Trivy secret + IaC (HIGH/CRITICAL) gates are blocking | `tests/unit/test_cicd_static.py` |

---

## 9. Decisions

- Reference domain (`tests/fixtures/reference_domain.py`) is the authoritative shape of domain interfaces until Trinity delivers `src/intake_domain`.
- Evaluation thresholds are frozen in `evaluation/scorecard.py::THRESHOLDS`.
- A threshold change requires a new approved baseline (POC-08).
- Azure integration tests are guarded by `INTAKE_RUN_AZURE_TESTS=1` environment variable.
- `tests/**` and `evaluation/**` are Switch's exclusive ownership per ADR-012.
- `.coveragerc` is the single authoritative coverage config (`source = src/intake_domain`, `fail_under = 80`); `pyproject.toml` deliberately does not declare a `[tool.coverage]` table, since coverage.py resolves `.coveragerc` first and a second table would be silently ignored.
- `pytest.ini` is the single authoritative pytest config for the same reason; `pyproject.toml` deliberately does not declare `[tool.pytest.ini_options]`.
- `ci.yml` is credential-free and dev-only: it never runs `-m azure` or `-m evaluation`, and never references Azure OIDC login. The private-network durability gate (`tests/azure`, `INTAKE_RUN_AZURE_TESTS=1`) and the evaluation/release gate (`eval.yaml`, `evaluation/`) are intentionally separate from this pipeline.
- `ci.yml`'s third-party Actions (`actions/checkout`, `actions/setup-python`, `actions/upload-artifact`, `aquasecurity/trivy-action`) are pinned to immutable 40-character commit SHAs, not mutable tags.
- Branch protection for `main` requires exactly one status check: `Required Checks` (job id `required-checks` in `ci.yml`). It depends on every other job and fails on any `failure`/`cancelled` result; only `integration-tests` may report `skipped` (it is intentionally PR-exempt).
