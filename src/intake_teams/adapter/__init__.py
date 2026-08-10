"""
Teams adapter — Activity Protocol contracts, auth boundary, and message parser.

Public surface:
  TeamsActivity       — inbound Activity Protocol payload from Bot Service
  CommandEnvelope     — translated command envelope sent to backend
  ActivityResponse    — outbound response sent back through Bot Service
  AuthBoundary        — webhook HMAC/JWT verification (rejects unauthenticated)
  ActivityParser      — maps TeamsActivity → CommandEnvelope
"""

from .auth import AuthBoundary, AuthError, ConfigurationError, DevModeWarning
from .contracts import (
    ActivityResponse,
    AdaptiveCardResponse,
    CommandActor,
    CommandEnvelope,
    ErrorResponse,
    InvokeResponse,
    MessageResponse,
    TeamsActivity,
    TeamsChannelAccount,
    TeamsConversationAccount,
    TeamsInvokeValue,
)
from .parser import ActivityParser, ParseError

__all__ = [
    "TeamsActivity",
    "TeamsChannelAccount",
    "TeamsConversationAccount",
    "TeamsInvokeValue",
    "CommandEnvelope",
    "CommandActor",
    "ActivityResponse",
    "AdaptiveCardResponse",
    "MessageResponse",
    "ErrorResponse",
    "InvokeResponse",
    "AuthBoundary",
    "AuthError",
    "ConfigurationError",
    "DevModeWarning",
    "ActivityParser",
    "ParseError",
]
