"""Root conftest — shared fixtures, import-resolution helpers."""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

# Make reference domain available to all tests
sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

from reference_domain import (  # noqa: E402
    ActorContext,
    FieldValue,
    Gap,
    GapCategory,
    GapSeverity,
    GapStatus,
    InMemoryIdempotencyStore,
    InMemoryRequestRepository,
    Request,
    RequestRevision,
    ValidationStatus,
    make_actor,
    make_request,
    make_revision,
)

# ---------------------------------------------------------------------------
# Module resolution helper
# ---------------------------------------------------------------------------

def _try_import(module_path: str):
    """Return the real module if importable, else None."""
    try:
        return importlib.import_module(module_path)
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Pytest markers
# ---------------------------------------------------------------------------

def pytest_configure(config):  # noqa: ANN001
    config.addinivalue_line("markers", "azure: requires Azure credentials")


def pytest_collection_modifyitems(config, items):  # noqa: ANN001
    if not os.environ.get("INTAKE_RUN_AZURE_TESTS"):
        skip_azure = pytest.mark.skip(
            reason="Set INTAKE_RUN_AZURE_TESTS=1 to run real-Azure tests"
        )
        for item in items:
            if item.get_closest_marker("azure"):
                item.add_marker(skip_azure)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def repo() -> InMemoryRequestRepository:
    return InMemoryRequestRepository()


@pytest.fixture()
def idempotency() -> InMemoryIdempotencyStore:
    return InMemoryIdempotencyStore()


@pytest.fixture()
def requester_actor() -> ActorContext:
    return make_actor(user_id="requester-1", roles=frozenset(["requester"]))


@pytest.fixture()
def reviewer_actor() -> ActorContext:
    return make_actor(user_id="reviewer-1", roles=frozenset(["reviewer"]))


@pytest.fixture()
def admin_actor() -> ActorContext:
    return make_actor(user_id="admin-1", roles=frozenset(["admin"]))


@pytest.fixture()
def new_request() -> Request:
    return make_request()


@pytest.fixture()
def new_revision(new_request: Request) -> RequestRevision:
    return make_revision(new_request.request_id)


@pytest.fixture()
def field_value() -> FieldValue:
    return FieldValue(
        field_path="project.name",
        value="Customer Portal Redesign",
        source_reference="user message turn 3",
        model_confidence=0.95,
        validation_status=ValidationStatus.VALID,
    )


@pytest.fixture()
def blocking_gap() -> Gap:
    return Gap(
        gap_id="gap-001",
        field_path="project.budget",
        category=GapCategory.MISSING,
        severity=GapSeverity.BLOCKING,
        status=GapStatus.OPEN,
    )


@pytest.fixture()
def warning_gap() -> Gap:
    return Gap(
        gap_id="gap-002",
        field_path="project.timeline.end_date",
        category=GapCategory.LOW_CONFIDENCE,
        severity=GapSeverity.WARNING,
        status=GapStatus.OPEN,
    )
