"""Shared behavior specification consumed by replaceable agent adapters."""

import json
from importlib.resources import files
from typing import Any, cast

BEHAVIOR_VERSION = "1.0"


def load_specification() -> dict[str, Any]:
    """Load the versioned behavior specification without runtime dependencies."""
    path = files("intake_agent_behavior").joinpath("behavior-v1.json")
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


__all__ = ["BEHAVIOR_VERSION", "load_specification"]
