"""Local Runtime REST Router (Phase 17).

Exposes:
  GET  /api/v1/voice-runtime/capabilities — snapshot of actual runtime capabilities
  POST /api/v1/voice-runtime/preflight/{project_id} — synchronous production preflight check
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Body
from pydantic import BaseModel, Field

from services.local_runtime_models import LocalRuntimeCapabilities, PreflightIssue
from services.local_runtime_service import LocalRuntimeService

router = APIRouter(prefix="/api/v1/voice-runtime", tags=["voice-runtime"])

_runtime_service = LocalRuntimeService()


class PreflightRequest(BaseModel):
    provider: str = "local"
    requested_formats: list[str] = Field(default_factory=lambda: ["wav"])


class PreflightResponse(BaseModel):
    project_id: str
    status: str  # "ok" | "blocked" | "warning"
    passed: bool
    issues: list[PreflightIssue] = Field(default_factory=list)


@router.get("/capabilities", response_model=LocalRuntimeCapabilities)
def get_runtime_capabilities() -> LocalRuntimeCapabilities:
    """Return a typed snapshot of the current local TTS runtime capabilities.

    Does not trigger model loading or network I/O.
    """
    return _runtime_service.get_capabilities()


@router.post("/preflight/{project_id}", response_model=PreflightResponse)
def run_production_preflight(
    project_id: str,
    body: PreflightRequest = Body(default_factory=PreflightRequest),
) -> PreflightResponse:
    """Validate all runtime preconditions before scheduling or executing a workflow."""
    issues = _runtime_service.run_production_preflight(
        project_id=project_id,
        provider=body.provider,
        requested_formats=body.requested_formats,
    )
    has_errors = any(i.severity == "error" for i in issues)
    has_warnings = any(i.severity == "warning" for i in issues)
    status = "blocked" if has_errors else ("warning" if has_warnings else "ok")
    return PreflightResponse(
        project_id=project_id,
        status=status,
        passed=not has_errors,
        issues=issues,
    )
