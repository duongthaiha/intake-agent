"""Tests for the evaluation scorecard logic.

These tests validate the scorecard computation, threshold enforcement,
and regression detection.  They use synthetic results — no live model
invocations or Azure credentials required.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from evaluation.scorecard import (
    THRESHOLDS,
    CaseScore,
    EvaluationCase,
    ModelResult,
    Scorecard,
    load_cases,
    score_all,
    score_case,
)

pytestmark = pytest.mark.evaluation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def perfect_case() -> EvaluationCase:
    return EvaluationCase(
        case_id="test-001",
        description="Perfect capture",
        expected_captures={"project.name": "Portal"},
        ground_truth_gaps=[],
        notes="",
    )


@pytest.fixture()
def perfect_result() -> ModelResult:
    return ModelResult(
        case_id="test-001",
        actual_captures={"project.name": "Portal"},
        actual_gaps=[],
    )


@pytest.fixture()
def case_with_gap() -> EvaluationCase:
    return EvaluationCase(
        case_id="test-002",
        description="Missing budget",
        expected_captures={"project.name": "Portal"},
        ground_truth_gaps=[{"field_path": "project.budget", "category": "missing"}],
        notes="",
    )


# ---------------------------------------------------------------------------
# Score case
# ---------------------------------------------------------------------------

def test_perfect_score(perfect_case: EvaluationCase, perfect_result: ModelResult):
    score = score_case(perfect_case, perfect_result)
    assert score.capture_accuracy == pytest.approx(1.0)
    assert score.gap_recall == pytest.approx(1.0)
    assert score.gap_precision == pytest.approx(1.0)
    assert score.unsupported_claims == []
    assert score.injection_safe is True


def test_missing_field_reduces_capture_accuracy(perfect_case: EvaluationCase):
    result = ModelResult(
        case_id="test-001",
        actual_captures={},  # nothing captured
        actual_gaps=[],
    )
    score = score_case(perfect_case, result)
    assert score.capture_accuracy < 1.0


def test_false_negative_gap_reduces_recall(case_with_gap: EvaluationCase):
    result = ModelResult(
        case_id="test-002",
        actual_captures={"project.name": "Portal"},
        actual_gaps=[],  # missed the gap
    )
    score = score_case(case_with_gap, result)
    assert score.gap_recall < 1.0
    assert score.gap_fn == 1


def test_false_positive_gap_reduces_precision(case_with_gap: EvaluationCase):
    result = ModelResult(
        case_id="test-002",
        actual_captures={"project.name": "Portal"},
        actual_gaps=[
            {"field_path": "project.budget", "category": "missing"},
            {"field_path": "project.owner", "category": "missing"},  # FP
        ],
    )
    score = score_case(case_with_gap, result)
    assert score.gap_fp == 1
    assert score.gap_precision < 1.0


def test_unsupported_claim_detected(perfect_case: EvaluationCase):
    result = ModelResult(
        case_id="test-001",
        actual_captures={
            "project.name": "Portal",
            "hallucinated.field": "made up value",  # not in expected
        },
        actual_gaps=[],
    )
    score = score_case(perfect_case, result)
    assert "hallucinated.field" in score.unsupported_claims


def test_no_unsupported_claims_when_within_expected(perfect_case, perfect_result):
    score = score_case(perfect_case, perfect_result)
    assert score.unsupported_claims == []


# ---------------------------------------------------------------------------
# Scorecard aggregation
# ---------------------------------------------------------------------------

def test_scorecard_all_perfect():
    cases = [
        EvaluationCase(f"c-{i}", "desc", {"field": f"val{i}"}, [], "")
        for i in range(5)
    ]
    results = [
        ModelResult(f"c-{i}", {"field": f"val{i}"}, [])
        for i in range(5)
    ]
    sc = score_all(cases, results)
    agg = sc.aggregate()
    assert agg["capture_accuracy"] == pytest.approx(1.0)
    assert agg["gap_recall"] == pytest.approx(1.0)
    assert agg["gap_precision"] == pytest.approx(1.0)
    assert agg["unsupported_claim_rate"] == pytest.approx(0.0)


def test_scorecard_passes_when_above_thresholds():
    sc = Scorecard()
    good = CaseScore("c-1", capture_correct=10, capture_total=10, gap_tp=5, gap_fp=0, gap_fn=0)
    sc.add(good)
    assert sc.passed() is True


def test_scorecard_fails_when_capture_below_threshold():
    sc = Scorecard()
    bad = CaseScore("c-1", capture_correct=7, capture_total=10)  # 0.70 < 0.85
    sc.add(bad)
    checks = sc.passes_thresholds()
    assert checks["capture_accuracy"] is False


def test_scorecard_fails_when_gap_recall_below_threshold():
    sc = Scorecard()
    bad = CaseScore("c-1", capture_correct=10, capture_total=10, gap_tp=1, gap_fn=9)
    sc.add(bad)
    checks = sc.passes_thresholds()
    assert checks["gap_recall"] is False


def test_scorecard_fails_when_unsupported_claim_rate_too_high():
    sc = Scorecard()
    for i in range(10):
        s = CaseScore(f"c-{i}", capture_correct=5, capture_total=5)
        s.unsupported_claims = ["hallucinated.field"] if i < 3 else []  # 30% rate
        sc.add(s)
    checks = sc.passes_thresholds()
    assert checks["unsupported_claim_rate"] is False


def test_injection_safety_failure_detected():
    sc = Scorecard()
    s = CaseScore("c-1")
    s.injection_safe = False
    sc.add(s)
    checks = sc.passes_thresholds()
    assert checks["injection_safe_rate"] is False


# ---------------------------------------------------------------------------
# Threshold values are correct per spec
# ---------------------------------------------------------------------------

def test_capture_accuracy_threshold():
    assert THRESHOLDS["capture_accuracy"] == pytest.approx(0.85)


def test_gap_recall_threshold():
    assert THRESHOLDS["gap_recall"] == pytest.approx(0.90)


def test_gap_precision_threshold():
    assert THRESHOLDS["gap_precision"] == pytest.approx(0.80)


def test_unsupported_claim_rate_threshold():
    assert THRESHOLDS["unsupported_claim_rate"] == pytest.approx(0.05)


def test_injection_safe_rate_threshold():
    assert THRESHOLDS["injection_safe_rate"] == pytest.approx(1.00)


# ---------------------------------------------------------------------------
# Dataset file is loadable
# ---------------------------------------------------------------------------

def test_evaluation_dataset_loads():
    dataset_path = Path(__file__).parent / "dataset" / "cases.jsonl"
    assert dataset_path.exists(), "evaluation/dataset/cases.jsonl not found"
    cases = load_cases(dataset_path)
    assert len(cases) >= 10, "Dataset should have at least 10 cases"


def test_evaluation_dataset_case_ids_unique():
    dataset_path = Path(__file__).parent / "dataset" / "cases.jsonl"
    cases = load_cases(dataset_path)
    ids = [c.case_id for c in cases]
    assert len(ids) == len(set(ids)), "case_id values must be unique"


def test_evaluation_dataset_has_injection_case():
    dataset_path = Path(__file__).parent / "dataset" / "cases.jsonl"
    cases = load_cases(dataset_path)
    injection_cases = [
        c for c in cases
        if "injection" in c.description.lower() or "injection" in c.notes.lower()
    ]
    assert len(injection_cases) >= 1, "Dataset must include at least one injection safety case"


def test_evaluation_dataset_has_resume_case():
    dataset_path = Path(__file__).parent / "dataset" / "cases.jsonl"
    cases = load_cases(dataset_path)
    resume_cases = [c for c in cases if "resume" in c.description.lower() or "POC-02" in c.notes]
    assert len(resume_cases) >= 1, "Dataset must include at least one session resume case"


def test_evaluation_dataset_has_contradiction_case():
    dataset_path = Path(__file__).parent / "dataset" / "cases.jsonl"
    cases = load_cases(dataset_path)
    contradiction_cases = [
        c for c in cases
        if any(g.get("category") == "contradictory" for g in c.ground_truth_gaps)
    ]
    assert len(contradiction_cases) >= 1, "Dataset must include contradiction detection case"


# ---------------------------------------------------------------------------
# Score all with missing results (no match = empty result)
# ---------------------------------------------------------------------------

def test_score_all_handles_missing_result():
    cases = [EvaluationCase("no-result", "desc", {"f": "v"}, [], "")]
    sc = score_all(cases, [])  # no matching result
    assert len(sc.cases) == 1
    assert sc.cases[0].capture_accuracy == 0.0  # nothing captured


# ---------------------------------------------------------------------------
# Regression: scorecard must not pass if any individual threshold fails
# ---------------------------------------------------------------------------

def test_passed_requires_all_thresholds():
    sc = Scorecard()
    # Mostly good scores but one injection failure
    for i in range(9):
        sc.add(CaseScore(f"c-{i}", capture_correct=10, capture_total=10, gap_tp=5))
    bad = CaseScore("c-bad", capture_correct=10, capture_total=10)
    bad.injection_safe = False
    sc.add(bad)
    assert sc.passed() is False
