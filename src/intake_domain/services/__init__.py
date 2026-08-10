"""Domain services: lifecycle state machine, validation, gap detection."""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from intake_domain.entities import (
    ActorContext,
    FieldSchema,
    Gap,
    GapCategory,
    GapSeverity,
    GapStatus,
    RequestRevision,
    RequestStatus,
    TemplateVersion,
    ValidationStatus,
)
from intake_domain.errors import InvalidTransitionError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Valid state transitions (from → set of allowed destinations)
# ---------------------------------------------------------------------------

_TRANSITIONS: dict[RequestStatus, set[RequestStatus]] = {
    RequestStatus.NEW: {RequestStatus.IN_REVIEW},
    RequestStatus.IN_REVIEW: {
        RequestStatus.APPROVED,
        RequestStatus.REJECTED,
        RequestStatus.AWAITING_FEEDBACK,
    },
    RequestStatus.AWAITING_FEEDBACK: {RequestStatus.IN_REVIEW},
    RequestStatus.APPROVED: {RequestStatus.COMPLETED},
    RequestStatus.REJECTED: set(),
    RequestStatus.COMPLETED: set(),
}

_MUTABLE_STATUSES = {RequestStatus.NEW, RequestStatus.AWAITING_FEEDBACK}


class LifecycleService:
    """Enforces the state machine and field-mutation rules."""

    def assert_transition(
        self,
        current: RequestStatus,
        target: RequestStatus,
        actor: ActorContext,
    ) -> None:
        allowed = _TRANSITIONS.get(current, set())
        if target not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition from {current.value!r} to {target.value!r}",
                current_status=current.value,
                target_status=target.value,
            )

    def assert_mutable(self, current: RequestStatus) -> None:
        if current not in _MUTABLE_STATUSES:
            raise InvalidTransitionError(
                f"Request in status {current.value!r} cannot be modified",
                current_status=current.value,
            )

    def allowed_actions(self, status: RequestStatus, roles: frozenset[str]) -> list[str]:
        actions: list[str] = []
        if status in _MUTABLE_STATUSES:
            actions.extend(["propose_field_updates", "get_context"])
        if status in _MUTABLE_STATUSES:
            actions.append("submit_for_review")
        if status == RequestStatus.IN_REVIEW and "reviewer" in roles:
            actions.append("record_review_decision")
        if status != RequestStatus.COMPLETED:
            actions.append("list_requests")
        return actions


# ---------------------------------------------------------------------------
# Validation service
# ---------------------------------------------------------------------------

class ValidationService:
    """Validates field values against template schema rules."""

    def validate_field(self, schema: FieldSchema, value: Any) -> tuple[ValidationStatus, str]:
        """Returns (status, error_message)."""
        if value is None:
            if schema.required:
                return ValidationStatus.INVALID, "Required field is missing"
            return ValidationStatus.VALID, ""

        if schema.field_type == "number":
            try:
                float(value)
            except (TypeError, ValueError):
                return ValidationStatus.INVALID, f"Expected number, got {type(value).__name__}"

        if (
            schema.field_type == "enum"
            and schema.enum_values
            and str(value) not in schema.enum_values
        ):
            return ValidationStatus.INVALID, (
                f"Value {value!r} not in allowed values: {schema.enum_values}"
            )

        if schema.field_type == "boolean" and not isinstance(value, bool):
            lower = str(value).lower()
            if lower not in {"true", "false", "yes", "no", "1", "0"}:
                return ValidationStatus.INVALID, f"Expected boolean, got {value!r}"

        return ValidationStatus.VALID, ""

    def validate_updates(
        self,
        template: TemplateVersion,
        updates: list[tuple[str, Any]],
    ) -> dict[str, tuple[ValidationStatus, str]]:
        """Returns field_path → (status, message) for each update."""
        schema_map = {f.field_path: f for f in template.fields}
        results: dict[str, tuple[ValidationStatus, str]] = {}
        for field_path, value in updates:
            if field_path not in schema_map:
                results[field_path] = (ValidationStatus.INVALID, "Unknown field path")
            else:
                results[field_path] = self.validate_field(schema_map[field_path], value)
        return results


# ---------------------------------------------------------------------------
# Gap detection service
# ---------------------------------------------------------------------------

class GapDetectionService:
    """Deterministic gap detection based on template schema and revision state."""

    def detect_gaps(
        self,
        template: TemplateVersion,
        revision: RequestRevision,
    ) -> list[Gap]:
        """Return the full set of open gaps for the current revision."""
        gaps: list[Gap] = []
        for schema in template.fields:
            field_val = revision.fields.get(schema.field_path)

            # Missing required field
            if schema.required and (field_val is None or field_val.value is None):
                gap_id = _stable_gap_id(revision.request_id, schema.field_path, "missing")
                existing = _find_gap(revision.gaps, schema.field_path, GapCategory.MISSING)
                if existing is None or existing.status == GapStatus.OPEN:
                    gaps.append(
                        Gap(
                            gap_id=gap_id,
                            field_path=schema.field_path,
                            category=GapCategory.MISSING,
                            severity=GapSeverity.BLOCKING,
                            status=GapStatus.OPEN,
                            message=f"Required field '{schema.field_path}' is missing",
                        )
                    )
                continue

            # Low-confidence field
            if (
                field_val is not None
                and field_val.model_confidence is not None
                and field_val.model_confidence < schema.min_confidence
            ):
                gap_id = _stable_gap_id(
                    revision.request_id, schema.field_path, "low_confidence"
                )
                existing = _find_gap(
                    revision.gaps, schema.field_path, GapCategory.LOW_CONFIDENCE
                )
                if existing is None or existing.status == GapStatus.OPEN:
                    gaps.append(
                        Gap(
                            gap_id=gap_id,
                            field_path=schema.field_path,
                            category=GapCategory.LOW_CONFIDENCE,
                            severity=GapSeverity.WARNING,
                            status=GapStatus.OPEN,
                            message=(
                                f"Confidence {field_val.model_confidence:.2f} "
                                f"below threshold {schema.min_confidence}"
                            ),
                        )
                    )

        return gaps

    def has_blocking_gaps(self, gaps: list[Gap]) -> bool:
        return any(
            g.severity == GapSeverity.BLOCKING and g.status == GapStatus.OPEN
            for g in gaps
        )

    def compute_quality_score(
        self, template: TemplateVersion, revision: RequestRevision
    ) -> float:
        if not template.fields:
            return 1.0
        filled = sum(
            1
            for f in template.fields
            if revision.fields.get(f.field_path) is not None
            and revision.fields[f.field_path].value is not None
        )
        return filled / len(template.fields)


def _stable_gap_id(request_id: str, field_path: str, category: str) -> str:
    raw = f"{request_id}:{field_path}:{category}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _find_gap(
    gaps: list[Gap], field_path: str, category: GapCategory
) -> Gap | None:
    return next(
        (g for g in gaps if g.field_path == field_path and g.category == category),
        None,
    )
