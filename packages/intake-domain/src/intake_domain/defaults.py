"""Canonical deterministic domain defaults shared by composition roots."""

from intake_domain.models import (
    ContradictionRule,
    FieldKind,
    TemplateField,
    TemplateVersion,
)


def default_template() -> TemplateVersion:
    return TemplateVersion(
        template_id="software-request",
        version="1.0",
        schema_version="1.0",
        fields=(
            TemplateField(
                "title",
                "Request title",
                FieldKind.TEXT,
                required=True,
                minimum_length=3,
                maximum_length=120,
            ),
            TemplateField(
                "business_need",
                "Business need",
                FieldKind.TEXT,
                required=True,
                minimum_length=10,
                maximum_length=2000,
            ),
            TemplateField(
                "urgency",
                "Urgency",
                FieldKind.CHOICE,
                required=True,
                choices=("low", "medium", "high"),
            ),
            TemplateField(
                "budget",
                "Budget",
                FieldKind.NUMBER,
                required=True,
                minimum_number=0,
            ),
            TemplateField(
                "requested_date",
                "Requested date",
                FieldKind.DATE,
                required=False,
            ),
            TemplateField(
                "must_complete_by",
                "Must complete by",
                FieldKind.DATE,
                required=False,
            ),
        ),
        contradiction_rules=(
            ContradictionRule(
                "requested_date",
                "date_after",
                "must_complete_by",
                "Requested date cannot be after the must-complete-by date.",
            ),
        ),
        quality_threshold=1.0,
        confidence_threshold=0.7,
        maximum_clarification_attempts=3,
        mandatory_handover=True,
    )
