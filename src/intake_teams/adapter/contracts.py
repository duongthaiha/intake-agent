"""
Activity Protocol contracts for the Teams adapter boundary.

These Pydantic models translate Bot Framework Activity objects
(sent by Azure Bot Service / Teams) into the backend command envelope
without coupling to any concrete backend package.

References:
  Bot Framework Activity schema v3:
    https://github.com/microsoft/botframework-sdk/blob/main/specs/botframework-activity/botframework-activity.md
  Teams Bot Framework channel:
    https://learn.microsoft.com/en-us/microsoftteams/platform/bots/bot-basics
  Command envelope schema:
    docs/contracts/command-event-schemas.md
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Inbound — Bot Framework Activity Protocol
# ---------------------------------------------------------------------------


class ActivityType(StrEnum):
    MESSAGE = "message"
    INVOKE = "invoke"
    CONVERSATION_UPDATE = "conversationUpdate"
    END_OF_CONVERSATION = "endOfConversation"
    TYPING = "typing"
    EVENT = "event"


class TeamsChannelAccount(BaseModel):
    """Represents a user or bot account in a Teams channel."""

    id: str = Field(description="Entra OID or bot app ID")
    name: str | None = None
    aad_object_id: str | None = Field(None, alias="aadObjectId")
    tenant_id: str | None = Field(None, alias="tenantId")

    model_config = {"populate_by_name": True}


class TeamsConversationAccount(BaseModel):
    """Represents a Teams conversation (channel, group chat, personal)."""

    id: str
    conversation_type: str | None = Field(None, alias="conversationType")
    is_group: bool = Field(False, alias="isGroup")
    tenant_id: str | None = Field(None, alias="tenantId")

    model_config = {"populate_by_name": True}


class TeamsChannelData(BaseModel):
    """Teams-specific channel data attached to an activity."""

    tenant: dict[str, str] | None = None  # {"id": "<tenant-id>"}
    channel: dict[str, str] | None = None  # {"id": "<channel-id>"}
    team: dict[str, str] | None = None  # {"id": "<team-id>"}

    @property
    def tenant_id(self) -> str | None:
        return self.tenant.get("id") if self.tenant else None


class TeamsInvokeValue(BaseModel):
    """
    Parsed value from an Adaptive Card Action.Submit or Action.Execute invoke.

    Teams sends Action.Execute as an invoke activity with:
      name = "adaptiveCard/action"
      value = { action: { type, verb, data } }

    Teams sends Action.Submit as a message activity (legacy) or invoke.
    """

    action_type: str | None = Field(None, alias="type")
    verb: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class TeamsActivity(BaseModel):
    """
    Inbound Bot Framework Activity from Teams/Azure Bot Service.

    Only fields relevant to the intake adapter are modelled; unknown fields
    are accepted via model_config extra="allow" for forward-compatibility.
    """

    id: str | None = None  # activity_id
    type: ActivityType
    timestamp: datetime | None = None
    service_url: str | None = Field(None, alias="serviceUrl")
    channel_id: str | None = Field(None, alias="channelId")
    from_account: TeamsChannelAccount | None = Field(None, alias="from")
    recipient: TeamsChannelAccount | None = None
    conversation: TeamsConversationAccount | None = None
    channel_data: TeamsChannelData | None = Field(None, alias="channelData")
    text: str | None = None
    value: dict[str, Any] | None = None  # invoke / card action payload
    name: str | None = None  # invoke name (e.g. "adaptiveCard/action")
    relay_token: str | None = Field(None, alias="relayToken")

    model_config = {"populate_by_name": True, "extra": "allow"}

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------

    @property
    def user_id(self) -> str:
        """Entra OID of the acting user. Falls back to from.id."""
        if self.from_account:
            return self.from_account.aad_object_id or self.from_account.id
        return "unknown"

    @property
    def tenant_id(self) -> str:
        """Tenant ID from channel_data > from > conversation, in that order."""
        if self.channel_data and self.channel_data.tenant_id:
            return self.channel_data.tenant_id
        if self.from_account and self.from_account.tenant_id:
            return self.from_account.tenant_id
        if self.conversation and self.conversation.tenant_id:
            return self.conversation.tenant_id
        return "unknown"

    @property
    def conversation_id(self) -> str:
        return self.conversation.id if self.conversation else "unknown"

    @property
    def activity_id(self) -> str:
        return self.id or str(uuid.uuid4())

    @property
    def is_invoke(self) -> bool:
        return self.type == ActivityType.INVOKE

    @property
    def is_message(self) -> bool:
        return self.type == ActivityType.MESSAGE

    def parse_invoke_value(self) -> TeamsInvokeValue | None:
        """Extract and validate invoke action data for adaptiveCard/action."""
        if not self.is_invoke or not self.value:
            return None
        action = self.value.get("action", self.value)
        return TeamsInvokeValue.model_validate(action)


# ---------------------------------------------------------------------------
# Outbound command envelope
# ---------------------------------------------------------------------------


class CommandActor(BaseModel):
    """Actor context derived from the verified Teams identity."""

    user_id: str
    tenant_id: str
    actor_type: Literal["user"] = "user"
    agent_identity: str = "foundry-agent"


class CommandEnvelope(BaseModel):
    """
    Translated command envelope — what the backend receives.

    Shape matches docs/contracts/command-event-schemas.md § Command envelope.
    The adapter produces this; no backend package is imported.
    """

    command_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    command_type: str
    request_id: str
    expected_revision: int | None = None
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    idempotency_key: str | None = None
    actor: CommandActor
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    data: dict[str, Any] = Field(default_factory=dict)
    activity_id: str | None = None  # Teams activity_id for correlation

    def __post_init__(self) -> None:
        if self.idempotency_key is None:
            self.idempotency_key = self.command_id


# ---------------------------------------------------------------------------
# Outbound response types — sent back through Bot Service
# ---------------------------------------------------------------------------


class MessageResponse(BaseModel):
    """Plain-text or markdown message response."""

    type: Literal["message"] = "message"
    text: str
    speak: str | None = None  # For voice / screen-reader narration


class AdaptiveCardResponse(BaseModel):
    """
    Bot Framework activity attachment wrapping an Adaptive Card.

    The `card` field holds the raw Adaptive Card JSON object.
    """

    type: Literal["adaptiveCard"] = "adaptiveCard"
    card: dict[str, Any]
    fallback_text: str | None = Field(
        None,
        description="Screen-reader / notification text when card cannot render",
    )


class ErrorResponse(BaseModel):
    """Error feedback rendered to the user via a status card or plain message."""

    type: Literal["error"] = "error"
    error_code: str
    message: str
    retry_eligible: bool = False
    current_revision: int | None = None


class InvokeResponse(BaseModel):
    """
    Response to an invoke activity (Action.Execute).

    status 200 = card accepted; the body is an optional updated card.
    status 400 = validation error displayed inline.
    """

    status: int = 200
    body: AdaptiveCardResponse | ErrorResponse | None = None


ActivityResponse = MessageResponse | AdaptiveCardResponse | ErrorResponse | InvokeResponse
