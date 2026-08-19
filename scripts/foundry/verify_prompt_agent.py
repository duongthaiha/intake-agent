"""Verify the deployed prompt intake agent against its source definition."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from intake_mcp.deployment import load_resolved_agent, verify_prompt_agent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--connection-name", required=True)
    args = parser.parse_args()

    root = Path(__file__).parents[2]
    manifest = root / "agents" / "prompt-intake-agent" / "agent.json"
    expected = load_resolved_agent(
        manifest,
        {
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": args.model,
            "INTAKE_MCP_SERVER_URL": args.server_url,
            "INTAKE_MCP_CONNECTION_NAME": args.connection_name,
        },
    )
    print(
        json.dumps(
            verify_prompt_agent(args.project_endpoint, expected),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
