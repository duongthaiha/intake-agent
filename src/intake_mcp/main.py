"""ASGI entry point for the private prompt-agent MCP service."""

from intake_mcp.server import build_http_app

app = build_http_app()
