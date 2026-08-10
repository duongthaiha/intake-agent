"""Tests for intake_teams.demo (local fixture/demo runner).

Imports demo/__main__.py to cover module-level statements, and calls
main() to exercise the full demo scenario including card loading, parsing,
and auth boundary checks — all without Azure credentials.
"""

from __future__ import annotations

import importlib
import sys

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.filterwarnings("ignore::ResourceWarning")]


def test_demo_main_returns_zero():
    """main() must return 0 when all checks pass."""
    from intake_teams.demo import main

    result = main(verbose=False)
    assert result == 0


def test_demo_main_verbose_returns_zero(capsys):
    """main(verbose=True) still exits 0 and produces output."""
    from intake_teams.demo import main

    result = main(verbose=True)
    assert result == 0
    captured = capsys.readouterr()
    assert "PASS" in captured.out


def test_demo_main_module_imports():
    """Importing intake_teams.demo.__main__ must not raise."""
    # If already imported, ensure it can be re-imported cleanly
    if "intake_teams.demo.__main__" in sys.modules:
        del sys.modules["intake_teams.demo.__main__"]
    mod = importlib.import_module("intake_teams.demo.__main__")
    assert hasattr(mod, "main")
