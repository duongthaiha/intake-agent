"""Deterministic benchmark scoring and fail-closed release decisions."""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

JsonObject = dict[str, Any]

REQUIRED_VARIANT_METRICS = {
    "field_capture_accuracy",
    "required_gap_recall",
    "false_positive_gap_rate",
    "contradiction_precision",
    "contradiction_recall",
    "clarification_relevance",
    "clarification_repetition_rate",
    "groundedness",
    "completion_rate",
    "reviewer_acceptance",
}
REQUIRED_DIFFERENTIAL_METRICS = {
    "field_agreement",
    "gap_agreement",
    "contradiction_agreement",
    "question_intent_agreement",
    "outcome_agreement",
}
REQUIRED_VERSION_FIELDS = {
    "hosted_agent",
    "prompt_agent",
    "model",
    "instructions",
    "shared_behavior",
    "toolbox",
    "mcp_contract",
    "policy",
    "template",
    "schema",
    "deterministic_packages",
}


@dataclass(frozen=True)
class Ratio:
    numerator: int
    denominator: int
    empty_value: float = 1.0

    @property
    def value(self) -> float:
        if self.denominator == 0:
            return self.empty_value
        return self.numerator / self.denominator


def _normalized(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return " ".join(str(value).strip().casefold().split())


def _field_map(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): _normalized(item) for key, item in value.items()}


def _item_key(item: Any, keys: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(item, Mapping):
        return tuple("" for _ in keys)
    return tuple(_normalized(item.get(key)) for key in keys)


def _item_set(value: Any, keys: Sequence[str]) -> set[tuple[str, ...]]:
    if not isinstance(value, list):
        return set()
    return {_item_key(item, keys) for item in value}


def _string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {_normalized(item) for item in value if _normalized(item)}


def _mean(values: Iterable[float]) -> float | None:
    materialized = list(values)
    if not materialized:
        return None
    return sum(materialized) / len(materialized)


def _metric(value: float | None, numerator: int | None, denominator: int | None) -> JsonObject:
    return {
        "value": None if value is None else round(value, 6),
        "numerator": numerator,
        "denominator": denominator,
    }


def load_json(path: Path) -> JsonObject:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def load_jsonl(path: Path) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise TypeError(f"{path}:{line_number} must contain a JSON object")
        rows.append(value)
    return rows


def validate_dataset(cases: Sequence[Mapping[str, Any]], manifest: Mapping[str, Any]) -> None:
    ids = [str(case.get("case_id", "")) for case in cases]
    if not cases:
        raise ValueError("dataset must contain at least one case")
    if any(not case_id for case_id in ids):
        raise ValueError("every dataset case requires case_id")
    if len(ids) != len(set(ids)):
        raise ValueError("dataset case_id values must be unique")
    if manifest.get("case_count") != len(cases):
        raise ValueError("dataset manifest case_count does not match cases.jsonl")
    for case in cases:
        expected = case.get("expected")
        if not isinstance(expected, Mapping):
            raise TypeError(f"{case['case_id']} requires expected outcomes")
        required = {
            "fields",
            "gaps",
            "contradictions",
            "question_intents",
            "outcome",
            "reviewer_accepted",
        }
        missing = sorted(required - set(expected))
        if missing:
            raise ValueError(f"{case['case_id']} missing expected keys: {missing}")
        failures = case.get("critical_failures")
        if not isinstance(failures, list) or not failures:
            raise ValueError(f"{case['case_id']} requires critical_failures")


def _index_results(
    results: Sequence[Mapping[str, Any]],
) -> tuple[dict[tuple[str, str], Mapping[str, Any]], list[str]]:
    index: dict[tuple[str, str], Mapping[str, Any]] = {}
    errors: list[str] = []
    for result in results:
        key = (_normalized(result.get("variant")), str(result.get("case_id", "")))
        if not all(key):
            errors.append("result_missing_variant_or_case_id")
            continue
        if key in index:
            errors.append(f"duplicate_result:{key[0]}:{key[1]}")
            continue
        index[key] = result
    return index, errors


def _score_variant(
    variant: str,
    cases: Sequence[Mapping[str, Any]],
    result_index: Mapping[tuple[str, str], Mapping[str, Any]],
) -> tuple[dict[str, JsonObject], list[str], list[str]]:
    capture_correct = capture_total = 0
    required_gap_tp = required_gap_total = 0
    gap_fp = gap_predictions = 0
    contradiction_tp = contradiction_expected = contradiction_predictions = 0
    question_predictions = repeated_questions = 0
    question_relevance_scores: list[float] = []
    supported_fields = actual_field_total = 0
    outcome_correct = 0
    reviewer_correct = reviewer_total = 0
    missing_results: list[str] = []
    critical_failures: list[str] = []

    for case in cases:
        case_id = str(case["case_id"])
        result = result_index.get((variant, case_id))
        if result is None:
            missing_results.append(case_id)
            continue

        expected = case["expected"]
        expected_fields = _field_map(expected.get("fields"))
        actual_fields = _field_map(result.get("fields"))
        capture_total += len(expected_fields)
        capture_correct += sum(
            actual_fields.get(path) == value for path, value in expected_fields.items()
        )
        actual_field_total += len(actual_fields)
        supported_fields += sum(
            path in expected_fields and expected_fields[path] == value
            for path, value in actual_fields.items()
        )

        expected_gaps = _item_set(expected.get("gaps"), ("field_path", "category"))
        required_gaps = {
            gap
            for gap in expected_gaps
            if gap[1] in {"missing", "ambiguous", "contradictory", "low_confidence"}
        }
        actual_gaps = _item_set(result.get("gaps"), ("field_path", "category"))
        required_gap_total += len(required_gaps)
        required_gap_tp += len(required_gaps & actual_gaps)
        gap_predictions += len(actual_gaps)
        gap_fp += len(actual_gaps - expected_gaps)

        expected_contradictions = _item_set(
            expected.get("contradictions"), ("field_path",)
        )
        actual_contradictions = _item_set(
            result.get("contradictions"), ("field_path",)
        )
        contradiction_expected += len(expected_contradictions)
        contradiction_predictions += len(actual_contradictions)
        contradiction_tp += len(expected_contradictions & actual_contradictions)

        expected_questions = _string_set(expected.get("question_intents"))
        actual_questions = _string_set(result.get("question_intents"))
        question_predictions += len(actual_questions)
        if not expected_questions and not actual_questions:
            question_relevance_scores.append(1.0)
        elif expected_questions and not actual_questions:
            question_relevance_scores.append(0.0)
        else:
            overlap = len(expected_questions & actual_questions)
            precision = overlap / len(actual_questions)
            recall = overlap / len(expected_questions) if expected_questions else 1.0
            question_relevance_scores.append(
                0.0
                if precision + recall == 0.0
                else 2 * precision * recall / (precision + recall)
            )
        repeated = result.get("repeated_question_count", 0)
        if not isinstance(repeated, int) or repeated < 0:
            critical_failures.append(f"{case_id}:invalid_repeated_question_count")
        else:
            repeated_questions += repeated

        outcome_correct += _normalized(result.get("outcome")) == _normalized(
            expected.get("outcome")
        )
        if expected.get("reviewer_accepted") is not None:
            reviewer_total += 1
            reviewer_correct += result.get("reviewer_accepted") is expected.get(
                "reviewer_accepted"
            )

        if "critical_failures" not in result:
            critical_failures.append(f"{case_id}:missing_critical_failure_report")
        observed_failures = result.get("critical_failures")
        if not isinstance(observed_failures, list):
            critical_failures.append(f"{case_id}:invalid_critical_failures")
        else:
            critical_failures.extend(
                f"{case_id}:{_normalized(failure)}"
                for failure in observed_failures
                if _normalized(failure)
            )

    evaluated_count = len(cases) - len(missing_results)
    metrics = {
        "field_capture_accuracy": _metric(
            Ratio(capture_correct, capture_total, 0.0).value,
            capture_correct,
            capture_total,
        ),
        "required_gap_recall": _metric(
            Ratio(required_gap_tp, required_gap_total).value,
            required_gap_tp,
            required_gap_total,
        ),
        "false_positive_gap_rate": _metric(
            Ratio(gap_fp, gap_predictions, 0.0).value, gap_fp, gap_predictions
        ),
        "contradiction_precision": _metric(
            Ratio(contradiction_tp, contradiction_predictions).value,
            contradiction_tp,
            contradiction_predictions,
        ),
        "contradiction_recall": _metric(
            Ratio(contradiction_tp, contradiction_expected).value,
            contradiction_tp,
            contradiction_expected,
        ),
        "clarification_relevance": _metric(
            _mean(question_relevance_scores),
            None,
            len(question_relevance_scores),
        ),
        "clarification_repetition_rate": _metric(
            Ratio(repeated_questions, question_predictions, 0.0).value,
            repeated_questions,
            question_predictions,
        ),
        "groundedness": _metric(
            Ratio(supported_fields, actual_field_total).value,
            supported_fields,
            actual_field_total,
        ),
        "completion_rate": _metric(
            Ratio(outcome_correct, evaluated_count, 0.0).value,
            outcome_correct,
            evaluated_count,
        ),
        "reviewer_acceptance": _metric(
            None if reviewer_total == 0 else reviewer_correct / reviewer_total,
            reviewer_correct,
            reviewer_total,
        ),
    }
    return metrics, sorted(missing_results), sorted(set(critical_failures))


def _jaccard(left: set[Any], right: set[Any]) -> float:
    if not left and not right:
        return 1.0
    return len(left & right) / len(left | right)


def _score_differential(
    variants: Sequence[str],
    cases: Sequence[Mapping[str, Any]],
    result_index: Mapping[tuple[str, str], Mapping[str, Any]],
) -> dict[str, JsonObject]:
    if len(variants) != 2:
        return {}
    left_variant, right_variant = variants
    field_scores: list[float] = []
    gap_scores: list[float] = []
    contradiction_scores: list[float] = []
    question_scores: list[float] = []
    outcome_scores: list[float] = []
    for case in cases:
        case_id = str(case["case_id"])
        left = result_index.get((left_variant, case_id))
        right = result_index.get((right_variant, case_id))
        if left is None or right is None:
            continue
        field_scores.append(
            1.0 if _field_map(left.get("fields")) == _field_map(right.get("fields")) else 0.0
        )
        gap_scores.append(
            _jaccard(
                _item_set(left.get("gaps"), ("field_path", "category")),
                _item_set(right.get("gaps"), ("field_path", "category")),
            )
        )
        contradiction_scores.append(
            _jaccard(
                _item_set(left.get("contradictions"), ("field_path",)),
                _item_set(right.get("contradictions"), ("field_path",)),
            )
        )
        question_scores.append(
            _jaccard(
                _string_set(left.get("question_intents")),
                _string_set(right.get("question_intents")),
            )
        )
        outcome_scores.append(
            1.0
            if _normalized(left.get("outcome")) == _normalized(right.get("outcome"))
            else 0.0
        )
    denominator = len(outcome_scores)
    return {
        "field_agreement": _metric(_mean(field_scores), None, denominator),
        "gap_agreement": _metric(_mean(gap_scores), None, denominator),
        "contradiction_agreement": _metric(
            _mean(contradiction_scores), None, denominator
        ),
        "question_intent_agreement": _metric(
            _mean(question_scores), None, denominator
        ),
        "outcome_agreement": _metric(_mean(outcome_scores), None, denominator),
    }


def _check_thresholds(
    metrics: Mapping[str, Mapping[str, Any]],
    thresholds: Mapping[str, Mapping[str, Any]],
    scope: str,
) -> tuple[dict[str, JsonObject], list[str]]:
    checks: dict[str, JsonObject] = {}
    reasons: list[str] = []
    for name, rule in thresholds.items():
        metric = metrics.get(name)
        value = None if metric is None else metric.get("value")
        direction = rule.get("direction")
        threshold = rule.get("value")
        passed = False
        numeric_value: float | None = None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            candidate_value = float(value)
            if math.isfinite(candidate_value) and 0.0 <= candidate_value <= 1.0:
                numeric_value = candidate_value
        if numeric_value is not None and isinstance(threshold, (int, float)):
            if direction == "minimum":
                passed = numeric_value >= threshold
            elif direction == "maximum":
                passed = numeric_value <= threshold
        checks[name] = {
            "value": value,
            "direction": direction,
            "threshold": threshold,
            "passed": passed,
        }
        if not passed:
            reason = "missing_metric" if value is None else "threshold_failed"
            reasons.append(f"{scope}:{name}:{reason}")
    return checks, reasons


def _validate_threshold_set(
    value: Any, required_names: set[str], label: str
) -> tuple[Mapping[str, Mapping[str, Any]], list[str]]:
    if not isinstance(value, Mapping):
        return {}, [f"{label}_thresholds_missing"]
    reasons: list[str] = []
    actual_names = {str(name) for name in value}
    for name in sorted(required_names - actual_names):
        reasons.append(f"{label}:{name}:threshold_missing")
    for name in sorted(actual_names - required_names):
        reasons.append(f"{label}:{name}:unknown_threshold")
    for name, raw_rule in value.items():
        if not isinstance(raw_rule, Mapping):
            reasons.append(f"{label}:{name}:threshold_rule_invalid")
            continue
        if raw_rule.get("direction") not in {"minimum", "maximum"}:
            reasons.append(f"{label}:{name}:threshold_direction_invalid")
        threshold = raw_rule.get("value")
        if (
            not isinstance(threshold, (int, float))
            or isinstance(threshold, bool)
            or not math.isfinite(float(threshold))
            or not 0.0 <= threshold <= 1.0
        ):
            reasons.append(f"{label}:{name}:threshold_value_invalid")
    return value, reasons


def validate_passing_scorecard(
    scorecard: Mapping[str, Any], threshold_config: Mapping[str, Any]
) -> None:
    if threshold_config.get("baseline_status") != "approved":
        raise ValueError("threshold baseline is not approved")
    required_thresholds, reasons = _validate_threshold_set(
        threshold_config.get("required_metrics"),
        REQUIRED_VARIANT_METRICS,
        "variant",
    )
    differential_thresholds, differential_reasons = _validate_threshold_set(
        threshold_config.get("differential_metrics"),
        REQUIRED_DIFFERENTIAL_METRICS,
        "differential",
    )
    reasons.extend(differential_reasons)
    if scorecard.get("release_decision") != "pass":
        reasons.append("scorecard_release_decision_non_passing")
    critical_failures = scorecard.get("critical_failures")
    if not isinstance(critical_failures, list) or critical_failures:
        reasons.append("scorecard_critical_failures_invalid")
    candidate = scorecard.get("candidate")
    if not isinstance(candidate, Mapping):
        reasons.append("scorecard_candidate_missing")
    else:
        commit_sha = str(candidate.get("commit_sha", ""))
        if len(commit_sha) != 40 or any(
            character not in "0123456789abcdef" for character in commit_sha
        ):
            reasons.append("scorecard_candidate_sha_invalid")
        if candidate.get("deployment_variant") not in {"baseline", "hardened"}:
            reasons.append("scorecard_deployment_variant_invalid")
    versions = scorecard.get("versions")
    if not isinstance(versions, Mapping):
        reasons.append("scorecard_versions_missing")
    else:
        for name in sorted(
            field for field in REQUIRED_VERSION_FIELDS if not _normalized(versions.get(field))
        ):
            reasons.append(f"scorecard_version_missing:{name}")

    variants = scorecard.get("variants")
    if not isinstance(variants, Mapping) or set(variants) != {"hosted", "prompt"}:
        reasons.append("scorecard_variants_incomplete")
    else:
        for variant_name in ("hosted", "prompt"):
            variant = variants[variant_name]
            if not isinstance(variant, Mapping):
                reasons.append(f"{variant_name}:scorecard_variant_invalid")
                continue
            metrics = variant.get("metrics")
            if not isinstance(metrics, Mapping):
                reasons.append(f"{variant_name}:scorecard_metrics_missing")
                continue
            _, metric_reasons = _check_thresholds(
                metrics, required_thresholds, variant_name
            )
            reasons.extend(metric_reasons)
            missing_results = variant.get("missing_results")
            if (
                variant.get("passed") is not True
                or not isinstance(missing_results, list)
                or missing_results
            ):
                reasons.append(f"{variant_name}:scorecard_variant_non_passing")

    differential = scorecard.get("differential")
    if not isinstance(differential, Mapping):
        reasons.append("scorecard_differential_missing")
    else:
        metrics = differential.get("metrics")
        if not isinstance(metrics, Mapping):
            reasons.append("scorecard_differential_metrics_missing")
        else:
            _, metric_reasons = _check_thresholds(
                metrics, differential_thresholds, "differential"
            )
            reasons.extend(metric_reasons)
        if differential.get("passed") is not True:
            reasons.append("scorecard_differential_non_passing")
    if reasons:
        raise ValueError(f"scorecard failed canonical validation: {sorted(set(reasons))}")


def build_scorecard(
    cases: Sequence[Mapping[str, Any]],
    dataset_manifest: Mapping[str, Any],
    result_document: Mapping[str, Any],
    threshold_config: Mapping[str, Any],
) -> JsonObject:
    validate_dataset(cases, dataset_manifest)
    variants = threshold_config.get("variants")
    if not isinstance(variants, list) or len(variants) != 2:
        raise ValueError("threshold configuration requires exactly two variants")
    variant_names = [str(variant) for variant in variants]
    raw_results = result_document.get("results")
    if not isinstance(raw_results, list):
        raw_results = []
    result_index, index_errors = _index_results(raw_results)

    reasons = list(index_errors)
    allowed_case_ids = {str(case["case_id"]) for case in cases}
    allowed_variants = set(variant_names)
    for variant, case_id in result_index:
        if variant not in allowed_variants:
            reasons.append(f"unknown_result_variant:{variant}:{case_id}")
        if case_id not in allowed_case_ids:
            reasons.append(f"unknown_result_case:{variant}:{case_id}")
    run_status = _normalized(result_document.get("run_status"))
    if run_status != "succeeded":
        reasons.append(f"evaluation_run_status:{run_status or 'missing'}")
    if not _normalized(result_document.get("run_id")):
        reasons.append("evaluation_run_id_missing")
    candidate = result_document.get("candidate")
    if not isinstance(candidate, Mapping):
        reasons.append("candidate_metadata_missing")
    else:
        commit_sha = str(candidate.get("commit_sha", ""))
        if len(commit_sha) != 40 or any(
            character not in "0123456789abcdef" for character in commit_sha
        ):
            reasons.append("candidate_commit_sha_invalid")
        if candidate.get("deployment_variant") not in {"baseline", "hardened"}:
            reasons.append("candidate_deployment_variant_invalid")
    versions = result_document.get("versions")
    if not isinstance(versions, Mapping):
        reasons.append("version_metadata_missing")
    else:
        for name in sorted(
            field for field in REQUIRED_VERSION_FIELDS if not _normalized(versions.get(field))
        ):
            reasons.append(f"version_metadata_missing:{name}")
    if threshold_config.get("baseline_status") != "approved":
        reasons.append("threshold_baseline_not_approved")
    if dataset_manifest.get("approval", {}).get("status") != "approved":
        reasons.append("dataset_not_approved")

    required_thresholds, threshold_errors = _validate_threshold_set(
        threshold_config.get("required_metrics"),
        REQUIRED_VARIANT_METRICS,
        "variant",
    )
    reasons.extend(threshold_errors)
    differential_thresholds, differential_threshold_errors = _validate_threshold_set(
        threshold_config.get("differential_metrics"),
        REQUIRED_DIFFERENTIAL_METRICS,
        "differential",
    )
    reasons.extend(differential_threshold_errors)

    variant_output: dict[str, JsonObject] = {}
    all_critical_failures: list[str] = []
    for variant in variant_names:
        metrics, missing_results, critical_failures = _score_variant(
            variant, cases, result_index
        )
        checks, check_reasons = _check_thresholds(
            metrics, required_thresholds, variant
        )
        reasons.extend(check_reasons)
        reasons.extend(f"{variant}:missing_result:{case_id}" for case_id in missing_results)
        reasons.extend(
            f"{variant}:critical_failure:{failure}" for failure in critical_failures
        )
        all_critical_failures.extend(
            f"{variant}:{failure}" for failure in critical_failures
        )
        variant_output[variant] = {
            "case_count": len(cases),
            "evaluated_count": len(cases) - len(missing_results),
            "missing_results": missing_results,
            "metrics": metrics,
            "threshold_checks": checks,
            "passed": not missing_results
            and not critical_failures
            and all(check["passed"] for check in checks.values()),
        }

    differential_metrics = _score_differential(
        variant_names, cases, result_index
    )
    differential_checks, differential_reasons = _check_thresholds(
        differential_metrics, differential_thresholds, "differential"
    )
    reasons.extend(differential_reasons)
    reasons = sorted(set(reasons))
    decision = "pass" if not reasons else "fail"
    return {
        "schema_version": "1.0.0",
        "run_id": result_document.get("run_id"),
        "candidate": result_document.get("candidate", {}),
        "versions": result_document.get("versions", {}),
        "dataset": {
            "dataset_id": dataset_manifest.get("dataset_id"),
            "dataset_version": dataset_manifest.get("dataset_version"),
        },
        "threshold_set_version": threshold_config.get("threshold_set_version"),
        "variants": variant_output,
        "differential": {
            "metrics": differential_metrics,
            "threshold_checks": differential_checks,
            "passed": bool(differential_checks)
            and all(check["passed"] for check in differential_checks.values()),
        },
        "critical_failures": sorted(set(all_critical_failures)),
        "release_decision": decision,
        "decision_reasons": reasons,
    }


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--thresholds", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        manifest = load_json(args.dataset_dir / "manifest.json")
        cases = load_jsonl(args.dataset_dir / str(manifest.get("case_file", "")))
        scorecard = build_scorecard(
            cases,
            manifest,
            load_json(args.results),
            load_json(args.thresholds),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(scorecard, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"evaluation failed closed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"release_decision": scorecard["release_decision"]}))
    return 0 if scorecard["release_decision"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
