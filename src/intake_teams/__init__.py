"""
intake_teams — Teams adapter spike and publishing assets.

Standalone package: does NOT import intake_domain, intake_agent,
intake_persistence, intake_workers, or any Azure SDK.

Contents:
  adapter/   — Activity Protocol contracts, auth boundary, message parser
  cards/     — Adaptive Card JSON templates
  manifest/  — Teams app manifest template
  demo/      — Local fixture/demo runner (no Azure credentials required)
"""
