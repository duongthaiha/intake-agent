"""Poll an authenticated evaluation status endpoint and fail closed."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.scorecard import load_json, validate_passing_scorecard

JsonObject = dict[str, Any]
Fetch = Callable[[], JsonObject]


class EvaluationStatusError(RuntimeError):
    """Raised when remote evaluation cannot produce complete passing evidence."""


def validate_scorecard(
    scorecard: Mapping[str, Any], threshold_config: Mapping[str, Any]
) -> None:
    try:
        validate_passing_scorecard(scorecard, threshold_config)
    except ValueError as exc:
        raise EvaluationStatusError(str(exc)) from exc


def wait_for_scorecard(
    fetch: Fetch,
    threshold_config: Mapping[str, Any],
    timeout_seconds: float,
    poll_seconds: float,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> JsonObject:
    deadline = monotonic() + timeout_seconds
    while True:
        payload = fetch()
        status = str(payload.get("status", "")).casefold()
        if status in {"failed", "cancelled", "timed_out", "timeout"}:
            raise EvaluationStatusError(f"evaluation job ended with status {status}")
        if status == "succeeded":
            scorecard = payload.get("scorecard")
            if not isinstance(scorecard, dict):
                raise EvaluationStatusError("successful evaluation omitted scorecard")
            validate_scorecard(scorecard, threshold_config)
            return scorecard
        if status not in {"queued", "running"}:
            raise EvaluationStatusError(f"unknown or missing evaluation status: {status}")
        if monotonic() >= deadline:
            raise EvaluationStatusError("evaluation timed out before complete evidence was available")
        sleep(poll_seconds)


def _http_fetch(url: str, token: str) -> Fetch:
    def fetch() -> JsonObject:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            value = json.load(response)
        if not isinstance(value, dict):
            raise EvaluationStatusError("status endpoint returned a non-object")
        return value

    return fetch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--thresholds",
        type=Path,
        default=Path("evaluation/config/thresholds-v1.0.0.json"),
    )
    parser.add_argument("--timeout-seconds", type=float, default=3600)
    parser.add_argument("--poll-seconds", type=float, default=15)
    parser.add_argument("--token-env", default="EVALUATION_STATUS_TOKEN")
    args = parser.parse_args()
    token = os.environ.get(args.token_env)
    if not token:
        print(f"evaluation failed closed: {args.token_env} is missing", file=sys.stderr)
        return 1
    try:
        scorecard = wait_for_scorecard(
            _http_fetch(args.status_url, token),
            load_json(args.thresholds),
            args.timeout_seconds,
            args.poll_seconds,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(scorecard, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (
        OSError,
        ValueError,
        EvaluationStatusError,
        urllib.error.URLError,
    ) as exc:
        print(f"evaluation failed closed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
