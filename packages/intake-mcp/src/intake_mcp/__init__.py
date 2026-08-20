"""Local and authenticated production Intake Agent MCP surfaces."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from intake_mcp.auth import DelegatedJWTSettings, DelegatedJWTVerifier
    from intake_mcp.local_profile import LocalProfile
    from intake_mcp.production import ProductionMCPServer, ProductionMCPSettings

__all__ = [
    "LOCAL_REVIEWER_ID",
    "DelegatedJWTSettings",
    "DelegatedJWTVerifier",
    "LocalProfile",
    "ProductionMCPServer",
    "ProductionMCPSettings",
    "create_production_requester_server",
    "create_production_reviewer_server",
    "create_requester_server",
    "create_reviewer_server",
    "default_template",
]


def __getattr__(name: str) -> Any:
    if name in {"LOCAL_REVIEWER_ID", "LocalProfile", "default_template"}:
        return getattr(import_module("intake_mcp.local_profile"), name)
    if name in {"DelegatedJWTSettings", "DelegatedJWTVerifier"}:
        return getattr(import_module("intake_mcp.auth"), name)
    if name in {
        "ProductionMCPServer",
        "ProductionMCPSettings",
        "create_production_requester_server",
        "create_production_reviewer_server",
        "create_requester_server",
        "create_reviewer_server",
    }:
        return getattr(import_module("intake_mcp.production"), name)
    raise AttributeError(name)
