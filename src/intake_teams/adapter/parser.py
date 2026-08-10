"""
Activity Protocol parser — translates TeamsActivity → CommandEnvelope.

This module contains the only logic that touches Teams-specific details.
All output types are defined in contracts.py; no backend packages are imported.

Supported command mappings
--------------------------
Activity type / verb          → command_type
---------------------------------------------
message (text)                → get_or_create_request  (first turn)
adaptiveCard/action verb=capture_field  → propose_field_updates
adaptiveCard/action verb=submit_request → submit_for_review
adaptiveCard/action verb=review_decision→ record_review_decision
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from .contracts import (
    ActivityType,
    CommandActor,
    CommandEnvelope,
    TeamsActivity,
    TeamsInvokeValue,
)


class ParseError(ValueError):
    """Raised when a TeamsActivity cannot be translated to a CommandEnvelope."""


class ActivityParser:
    """
    Translates a verified TeamsActivity into a CommandEnvelope.

    The CommandEnvelope is the only thing the backend command bus receives;
    all Teams-specific identifiers are either encoded into the envelope
    fields or dropped (they are not needed downstream).
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(
        self,
        activity: TeamsActivity,
        *,
        agent_identity: str = "foundry-agent",
    ) -> CommandEnvelope:
        """
        Translate a TeamsActivity into a CommandEnvelope.

        Raises:
            ParseError: if the activity type/verb is not recognised.
        """
        if activity.type == ActivityType.MESSAGE:
            return self._parse_message(activity, agent_identity)
        if activity.type == ActivityType.INVOKE:
            return self._parse_invoke(activity, agent_identity)
        raise ParseError(
            f"Unsupported activity type: {activity.type!r}. "
            "Only 'message' and 'invoke' activities are handled."
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _make_actor(
        self, activity: TeamsActivity, agent_identity: str
    ) -> CommandActor:
        return CommandActor(
            user_id=activity.user_id,
            tenant_id=activity.tenant_id,
            agent_identity=agent_identity,
        )

    def _derive_request_id(self, activity: TeamsActivity) -> str:
        """
        Deterministic request_id: SHA-256( tenant_id + conversation_id ).

        Matches the derivation rule in ADR-013 § Core entities.
        """
        raw = f"{activity.tenant_id}:{activity.conversation_id}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def _base_envelope(
        self,
        activity: TeamsActivity,
        command_type: str,
        agent_identity: str,
        data: dict[str, Any] | None = None,
        expected_revision: int | None = None,
    ) -> CommandEnvelope:
        command_id = str(uuid.uuid4())
        return CommandEnvelope(
            command_id=command_id,
            command_type=command_type,
            request_id=self._derive_request_id(activity),
            expected_revision=expected_revision,
            correlation_id=str(uuid.uuid4()),
            idempotency_key=command_id,
            actor=self._make_actor(activity, agent_identity),
            data=data or {},
            activity_id=activity.activity_id,
        )

    # ---- Message activities -------------------------------------------

    def _parse_message(
        self, activity: TeamsActivity, agent_identity: str
    ) -> CommandEnvelope:
        text = (activity.text or "").strip()
        if not text:
            raise ParseError("Message activity has no text content")

        return self._base_envelope(
            activity,
            command_type="get_or_create_request",
            agent_identity=agent_identity,
            data={"message_text": text},
        )

    # ---- Invoke activities (Adaptive Card Action.Execute) -------------

    def _parse_invoke(
        self, activity: TeamsActivity, agent_identity: str
    ) -> CommandEnvelope:
        if activity.name != "adaptiveCard/action":
            raise ParseError(
                f"Unsupported invoke name: {activity.name!r}. "
                "Expected 'adaptiveCard/action'."
            )

        invoke = activity.parse_invoke_value()
        if invoke is None:
            raise ParseError("Invoke activity has no parseable value")

        verb = invoke.verb or invoke.data.get("verb") or ""
        dispatch = {
            "capture_field": self._parse_capture_field,
            "submit_request": self._parse_submit,
            "review_decision": self._parse_review_decision,
            "acknowledge_gaps": self._parse_acknowledge_gaps,
        }

        handler = dispatch.get(verb)
        if handler is None:
            raise ParseError(
                f"Unknown invoke verb: {verb!r}. "
                f"Expected one of: {sorted(dispatch)}"
            )
        return handler(activity, invoke, agent_identity)

    def _parse_capture_field(
        self,
        activity: TeamsActivity,
        invoke: TeamsInvokeValue,
        agent_identity: str,
    ) -> CommandEnvelope:
        """
        Action.Execute verb=capture_field
        Data shape: { field_path, value, [expected_revision] }
        """
        data = invoke.data
        field_path = data.get("field_path")
        value = data.get("value")
        if not field_path:
            raise ParseError("capture_field invoke missing 'field_path'")
        if value is None:
            raise ParseError("capture_field invoke missing 'value'")

        expected_revision = _int_or_none(data.get("expected_revision"))

        return self._base_envelope(
            activity,
            command_type="propose_field_updates",
            agent_identity=agent_identity,
            expected_revision=expected_revision,
            data={
                "updates": [
                    {
                        "field_path": field_path,
                        "value": value,
                        "source_reference": f"card action turn {activity.activity_id}",
                        "model_confidence": None,
                    }
                ]
            },
        )

    def _parse_submit(
        self,
        activity: TeamsActivity,
        invoke: TeamsInvokeValue,
        agent_identity: str,
    ) -> CommandEnvelope:
        """Action.Execute verb=submit_request"""
        expected_revision = _int_or_none(invoke.data.get("expected_revision"))
        return self._base_envelope(
            activity,
            command_type="submit_for_review",
            agent_identity=agent_identity,
            expected_revision=expected_revision,
            data={},
        )

    def _parse_review_decision(
        self,
        activity: TeamsActivity,
        invoke: TeamsInvokeValue,
        agent_identity: str,
    ) -> CommandEnvelope:
        """Action.Execute verb=review_decision"""
        data = invoke.data
        decision = data.get("decision")
        if decision not in ("approve", "reject", "request_changes"):
            raise ParseError(
                f"review_decision invoke has invalid 'decision': {decision!r}. "
                "Expected: approve | reject | request_changes"
            )
        return self._base_envelope(
            activity,
            command_type="record_review_decision",
            agent_identity=agent_identity,
            expected_revision=_int_or_none(data.get("expected_revision")),
            data={
                "decision": decision,
                "rationale": data.get("rationale", ""),
            },
        )

    def _parse_acknowledge_gaps(
        self,
        activity: TeamsActivity,
        invoke: TeamsInvokeValue,
        agent_identity: str,
    ) -> CommandEnvelope:
        """Action.Execute verb=acknowledge_gaps — user accepts listed warning gaps."""
        data = invoke.data
        gap_ids = data.get("gap_ids", [])
        if not isinstance(gap_ids, list):
            raise ParseError("acknowledge_gaps invoke 'gap_ids' must be a list")
        return self._base_envelope(
            activity,
            command_type="acknowledge_gaps",
            agent_identity=agent_identity,
            data={"gap_ids": gap_ids},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
