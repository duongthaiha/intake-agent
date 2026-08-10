"""Entry point for `python -m intake_teams.demo`."""

from __future__ import annotations

import sys

from intake_teams.demo import main

if __name__ == "__main__":
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    sys.exit(main(verbose=verbose))
