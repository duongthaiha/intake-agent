"""FastAPI HTTP entrypoint for local demo and integration testing.

Exposes the full vertical slice over HTTP without requiring Azure.
All persistence defaults to in-memory (INTAKE_PERSISTENCE_BACKEND=inmemory).

Run:
    uvicorn intake_agent.main:app --reload --port 8000

Or via the CLI script:
    intake-demo
"""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

from intake_agent.adapter.local import LocalAdapter
from intake_agent.config import build_repositories, get_settings

logger = structlog.get_logger(__name__)

_adapter: LocalAdapter | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _adapter
    settings = get_settings()
    repos = build_repositories(settings)
    _adapter = LocalAdapter(
        request_repo=repos["request_repo"],
        template_repo=repos["template_repo"],
        outbox_repo=repos["outbox_repo"],
        idempotency_store=repos["idempotency_store"],
        artifact_store=repos["artifact_store"],
        template_id=settings.template_id,
    )
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )
    logger.info(
        "intake_agent_started",
        environment=settings.environment,
        backend=settings.persistence_backend,
    )
    yield
    logger.info("intake_agent_stopped")


app = FastAPI(
    title="Intake Agent — Local Demo",
    description="Local HTTP adapter for the intake vertical slice. No Azure required.",
    version="0.1.0",
    lifespan=lifespan,
)


def _get_adapter() -> LocalAdapter:
    if _adapter is None:
        raise RuntimeError("Adapter not initialised")
    return _adapter


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CreateRequestBody(BaseModel):
    user_id: str = "local-user"
    conversation_id: str = "local-conv-1"


class ProposeUpdatesBody(BaseModel):
    expected_revision: int
    updates: list[dict[str, Any]]
    user_id: str = "local-user"


class SubmitBody(BaseModel):
    expected_revision: int
    user_id: str = "local-user"


class ReviewDecisionBody(BaseModel):
    expected_revision: int
    decision: str
    rationale: str
    reviewer_id: str = "local-reviewer"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/requests", status_code=status.HTTP_200_OK)
async def create_request(body: CreateRequestBody) -> dict[str, Any]:
    try:
        return await _get_adapter().get_or_create_request(
            user_id=body.user_id,
            conversation_id=body.conversation_id,
        )
    except Exception as exc:
        raise _to_http(exc) from exc


@app.get("/requests")
async def list_requests(user_id: str = "local-user") -> list[dict[str, Any]]:
    try:
        return await _get_adapter().list_requests(user_id=user_id)
    except Exception as exc:
        raise _to_http(exc) from exc


@app.get("/requests/{request_id}")
async def get_context(request_id: str, user_id: str = "local-user") -> dict[str, Any]:
    try:
        return await _get_adapter().get_context(request_id, user_id=user_id)
    except Exception as exc:
        raise _to_http(exc) from exc


@app.post("/requests/{request_id}/fields")
async def propose_updates(request_id: str, body: ProposeUpdatesBody) -> dict[str, Any]:
    try:
        return await _get_adapter().propose_updates(
            request_id=request_id,
            expected_revision=body.expected_revision,
            updates=body.updates,
            user_id=body.user_id,
        )
    except Exception as exc:
        raise _to_http(exc) from exc


@app.post("/requests/{request_id}/submit")
async def submit_for_review(request_id: str, body: SubmitBody) -> dict[str, Any]:
    try:
        return await _get_adapter().submit_for_review(
            request_id=request_id,
            expected_revision=body.expected_revision,
            user_id=body.user_id,
        )
    except Exception as exc:
        raise _to_http(exc) from exc


@app.post("/requests/{request_id}/review")
async def record_review(request_id: str, body: ReviewDecisionBody) -> dict[str, Any]:
    try:
        return await _get_adapter().record_review_decision(
            request_id=request_id,
            expected_revision=body.expected_revision,
            decision=body.decision,
            rationale=body.rationale,
            reviewer_id=body.reviewer_id,
        )
    except Exception as exc:
        raise _to_http(exc) from exc


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------

def _to_http(exc: Exception) -> HTTPException:
    from intake_domain.errors import (
        AuthorizationDeniedError,
        ConflictError,
        IntakeDomainError,
        InvalidTransitionError,
        NotFoundError,
        PreconditionFailedError,
        ValidationError,
    )

    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=404, detail=exc.to_dict())
    if isinstance(exc, AuthorizationDeniedError):
        return HTTPException(status_code=403, detail=exc.to_dict())
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=409, detail=exc.to_dict())
    if isinstance(exc, (ValidationError, InvalidTransitionError, PreconditionFailedError)):
        return HTTPException(status_code=422, detail=exc.to_dict())
    if isinstance(exc, IntakeDomainError):
        return HTTPException(status_code=500, detail=exc.to_dict())
    return HTTPException(status_code=500, detail={"error_code": "INTERNAL", "message": str(exc)})


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def cli() -> None:
    """CLI entry point: starts the uvicorn demo server."""
    import uvicorn
    uvicorn.run("intake_agent.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    cli()
