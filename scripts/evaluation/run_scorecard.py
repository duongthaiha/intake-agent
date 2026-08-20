"""Command-line wrapper for the repository evaluation scorecard."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.scorecard import main  # noqa: I001


if __name__ == "__main__":
    raise SystemExit(main())
