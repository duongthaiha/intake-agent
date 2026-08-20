# Quality and Evaluation Strategy

**Version:** 1.0
**Status:** Implemented for isolated evaluation tooling; deployed-system integration pending

## Gate model

Pull requests run lint, strict type checks, isolated evaluation tests, Python security scanning, secret scanning, and IaC checks when Bicep is present. The single `Required checks` job is the branch-protection target.

Release candidates use `.github/workflows/release.yml` on an approved, VNet-connected self-hosted runner. The workflow verifies an immutable commit on `main`, deploys only through `azd up`, runs runtime-owned smoke and cross-variant tests, starts the private evaluation job, waits no longer than 60 minutes, validates complete metrics, and verifies the signed evidence manifest. No PR result, local substitute, skipped job, scheduled quality run, or unsigned artifact substitutes for this gate.

## Test layers and ownership

| Layer | Current command or owner | Release evidence |
|---|---|---|
| Evaluation unit | `python -m unittest discover -s tests/evaluation -v` | Test log |
| Python syntax | `python -m compileall -q evaluation scripts/evaluation tests/evaluation` | CI result |
| Dataset structure | `tests/evaluation/test_dataset.py` | Dataset version and approval |
| Scorecard/release decision | `tests/evaluation/test_scorecard.py` | Machine-readable scorecard |
| Evidence integrity | `tests/evaluation/test_evidence.py` | Signed manifest plus artifact digests |
| Timeout/missing metric | `tests/evaluation/test_wait_for_scorecard.py` | Fail-closed workflow result |
| Runtime unit/contract/component | Runtime team; integrate existing commands into CI | JUnit/coverage reports |
| Bicep lint/build/scan/what-if | Infrastructure team; Bicep remains authoritative | Compiled/lint/scan/what-if output |
| Deployed smoke/E2E/cross-variant | Runtime-owned `scripts/release/post-deploy-smoke.sh` | Test report and transcript |
| Accessibility/performance/resilience | Product/runtime/operations owners | Versioned reports |
| Automated and human evaluation | Private evaluation job and blinded reviewers | Scorecard and rubric decisions |

## Metric formulas

Metrics are micro-averaged per variant unless stated otherwise.

| Metric | Formula | Direction |
|---|---|---|
| Field capture accuracy | Correct expected canonical field/value pairs / expected field/value pairs | Higher |
| Required-gap recall | Correct expected blocking/ambiguous/contradictory/low-confidence gaps / expected required gaps | Higher |
| False-positive gap rate | Predicted gaps absent from expected gaps / predicted gaps | Lower |
| Contradiction precision | Correct contradiction field paths / predicted contradiction field paths | Higher |
| Contradiction recall | Correct contradiction field paths / expected contradiction field paths | Higher |
| Clarification relevance | Case-average F1 of expected and actual question-intent sets | Higher |
| Clarification repetition rate | Repeated question count / unique question intents asked | Lower |
| Groundedness | Actual canonical fields with an expected value match / actual canonical fields | Higher |
| Completion rate | Cases with expected semantic outcome / evaluated cases | Higher |
| Reviewer acceptance | Cases matching reviewed acceptable behavior / reviewed cases | Higher |

An empty prediction set scores `1.0` only when there was nothing to predict; required omissions still reduce recall or completion. A metric with no eligible reviewed cases is missing and blocks release.

Differential metrics compare Hosted and Prompt semantic outputs by case: exact normalized fields and outcomes, plus Jaccard agreement for gaps, contradiction field paths, and question intents. Prose is intentionally excluded.

## Critical failures

Any observed privacy disclosure, authorization bypass, identity supplied by model arguments, unapproved state change, fabricated persistence success, data corruption/loss, arbitrary tool/code/query execution, policy or prompt-injection bypass, lost cross-variant state, or unsigned/tampered evidence blocks release regardless of aggregate metrics.

## Repeated runs

The runtime evaluation job owns repeated sampling for non-deterministic model behavior and must aggregate every configured repetition into one result document. It must not omit failed attempts. The repetition count, model/configuration versions, and aggregation policy belong in the signed evidence.
