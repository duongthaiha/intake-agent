"""
Cards package — Adaptive Card JSON templates.

Load helpers:
    from intake_teams.cards import load_card, load_all
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, cast

_HERE = pathlib.Path(__file__).parent


def load_card(name: str) -> dict[str, Any]:
    """
    Load an Adaptive Card template by filename (without .json extension).

    Example:
        card = load_card("create")
    """
    path = _HERE / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Adaptive Card template not found: {path}")
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def load_all() -> dict[str, dict[str, Any]]:
    """Return a mapping of {name: card_dict} for all bundled card templates."""
    return {
        p.stem: cast(dict[str, Any], json.loads(p.read_text(encoding="utf-8")))
        for p in sorted(_HERE.glob("*.json"))
    }
