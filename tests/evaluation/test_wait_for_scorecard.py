from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from typing import Any

from evaluation.scorecard import (
    REQUIRED_DIFFERENTIAL_METRICS,
    REQUIRED_VARIANT_METRICS,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "evaluation" / "wait_for_scorecard.py"
SPEC = importlib.util.spec_from_file_location("wait_for_scorecard", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def passing_scorecard() -> dict[str, Any]:
    metric_names = REQUIRED_VARIANT_METRICS
    differential_names = REQUIRED_DIFFERENTIAL_METRICS
    return {
        "release_decision": "pass",
        "critical_failures": [],
        "candidate": {
            "commit_sha": "a" * 40,
            "deployment_variant": "baseline",
        },
        "versions": {
            "hosted_agent": "1.0.0",
            "prompt_agent": "1.0.0",
            "model": "test-model",
            "instructions": "1.0.0",
            "shared_behavior": "1.0.0",
            "toolbox": "1.0.0",
            "mcp_contract": "1.0.0",
            "policy": "1.0.0",
            "template": "1.0.0",
            "schema": "1.0.0",
            "deterministic_packages": "1.0.0",
        },
        "variants": {
            variant: {
                "passed": True,
                "missing_results": [],
                "metrics": {
                    name: {
                        "value": (
                            0.0
                            if name
                            in {
                                "false_positive_gap_rate",
                                "clarification_repetition_rate",
                            }
                            else 1.0
                        )
                    }
                    for name in metric_names
                },
            }
            for variant in ("hosted", "prompt")
        },
        "differential": {
            "passed": True,
            "metrics": {name: {"value": 1.0} for name in differential_names},
        },
    }


def approved_thresholds() -> dict[str, Any]:
    path = ROOT / "evaluation" / "config" / "thresholds-v1.0.0.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["baseline_status"] = "approved"
    return value


class WaitForScorecardTests(unittest.TestCase):
    def test_success_requires_complete_scorecard(self) -> None:
        result = MODULE.wait_for_scorecard(
            lambda: {"status": "succeeded", "scorecard": passing_scorecard()},
            approved_thresholds(),
            timeout_seconds=1,
            poll_seconds=0,
        )
        self.assertEqual("pass", result["release_decision"])

    def test_missing_metric_fails_closed(self) -> None:
        scorecard = passing_scorecard()
        del scorecard["variants"]["hosted"]["metrics"]["groundedness"]
        with self.assertRaises(MODULE.EvaluationStatusError):
            MODULE.wait_for_scorecard(
                lambda: {"status": "succeeded", "scorecard": scorecard},
                approved_thresholds(),
                timeout_seconds=1,
                poll_seconds=0,
            )

    def test_failed_job_fails_closed(self) -> None:
        with self.assertRaises(MODULE.EvaluationStatusError):
            MODULE.wait_for_scorecard(
                lambda: {"status": "failed"},
                approved_thresholds(),
                timeout_seconds=1,
                poll_seconds=0,
            )

    def test_timeout_fails_closed(self) -> None:
        times = iter([0.0, 2.0])
        with self.assertRaises(MODULE.EvaluationStatusError):
            MODULE.wait_for_scorecard(
                lambda: {"status": "running"},
                approved_thresholds(),
                timeout_seconds=1,
                poll_seconds=0,
                monotonic=lambda: next(times),
                sleep=lambda _: None,
            )

    def test_forged_pass_flags_do_not_override_failing_metrics(self) -> None:
        scorecard = passing_scorecard()
        scorecard["variants"]["hosted"]["metrics"]["field_capture_accuracy"][
            "value"
        ] = 0.0
        with self.assertRaises(MODULE.EvaluationStatusError):
            MODULE.wait_for_scorecard(
                lambda: {"status": "succeeded", "scorecard": scorecard},
                approved_thresholds(),
                timeout_seconds=1,
                poll_seconds=0,
            )

    def test_missing_critical_failure_channel_fails_closed(self) -> None:
        scorecard = passing_scorecard()
        del scorecard["critical_failures"]
        with self.assertRaises(MODULE.EvaluationStatusError):
            MODULE.wait_for_scorecard(
                lambda: {"status": "succeeded", "scorecard": scorecard},
                approved_thresholds(),
                timeout_seconds=1,
                poll_seconds=0,
            )

    def test_impossible_metric_value_fails_closed(self) -> None:
        scorecard = passing_scorecard()
        scorecard["variants"]["hosted"]["metrics"]["field_capture_accuracy"][
            "value"
        ] = 2.0
        scorecard["variants"]["prompt"]["metrics"]["false_positive_gap_rate"][
            "value"
        ] = -1.0
        with self.assertRaises(MODULE.EvaluationStatusError):
            MODULE.wait_for_scorecard(
                lambda: {"status": "succeeded", "scorecard": scorecard},
                approved_thresholds(),
                timeout_seconds=1,
                poll_seconds=0,
            )

    def test_missing_results_channel_fails_closed(self) -> None:
        scorecard = passing_scorecard()
        del scorecard["variants"]["hosted"]["missing_results"]
        with self.assertRaises(MODULE.EvaluationStatusError):
            MODULE.wait_for_scorecard(
                lambda: {"status": "succeeded", "scorecard": scorecard},
                approved_thresholds(),
                timeout_seconds=1,
                poll_seconds=0,
            )


if __name__ == "__main__":
    unittest.main()
