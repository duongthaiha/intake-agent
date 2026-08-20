from __future__ import annotations

from evaluation.job import VERSION_FIELDS, _fallback_results


def test_fallback_results_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("EVALUATION_COMMIT_SHA", "a" * 40)

    results = _fallback_results("run-test")

    assert results["run_id"] == "run-test"
    assert results["run_status"] == "missing_results"
    assert results["results"] == []
    assert results["candidate"] == {
        "commit_sha": "a" * 40,
        "deployment_variant": "hardened",
    }
    assert set(results["versions"]) == set(VERSION_FIELDS)
