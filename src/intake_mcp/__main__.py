"""Run the private MCP service."""

import uvicorn

from intake_agent.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "intake_mcp.server:app",
        host=settings.mcp_host,
        port=settings.mcp_port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
