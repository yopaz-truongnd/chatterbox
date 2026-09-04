"""Local Runtime REST Router (Phases 17 & 21).

Exposes:
  GET  /api/v1/voice-runtime/capabilities — snapshot of actual runtime capabilities
  POST /api/v1/voice-runtime/preflight/{project_id} — synchronous production preflight check
  POST /api/v1/voice-runtime/validations — launch real-runtime production validation
  GET  /api/v1/voice-runtime/validations/{validation_id} — validation status and progress
  GET  /api/v1/voice-runtime/validations/{validation_id}/report — full validation report
  POST /api/v1/voice-runtime/validations/{validation_id}/cancel — cancel running validation
"""

from __future__ import annotations

import threading
from typing import Any
from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from services.local_runtime_models import LocalRuntimeCapabilities, PreflightIssue
from services.local_runtime_service import LocalRuntimeService
from services.production_validation_models import (
    ProductionValidationReport,
    ProductionValidationRequest,
    ValidationVerdict,
)
from services.production_validation_service import ProductionValidationService

router = APIRouter(prefix="/api/v1/voice-runtime", tags=["voice-runtime"])

_runtime_service = LocalRuntimeService()
_validation_service = ProductionValidationService()


class PreflightRequest(BaseModel):
    provider: str = "local"
    requested_formats: list[str] = Field(default_factory=lambda: ["wav"])
    selected_model: str | None = None
    reference_voice: str | None = None


class PreflightResponse(BaseModel):
    project_id: str
    status: str  # "ok" | "blocked" | "warning"
    passed: bool
    issues: list[PreflightIssue] = Field(default_factory=list)


class StartValidationResponse(BaseModel):
    validation_id: str
    status: str
    message: str


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
        selected_model=body.selected_model,
        reference_voice=body.reference_voice,
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


# =====================================================================
# Real Production Validation Endpoints (Phase 21)
# =====================================================================

@router.post("/validations", response_model=ProductionValidationReport)
def start_production_validation(
    request: ProductionValidationRequest = Body(default_factory=ProductionValidationRequest),
    sync: bool = Query(default=True, description="Run synchronously or async in background"),
) -> ProductionValidationReport:
    """Execute real-runtime production validation against local runtime."""
    if sync:
        return _validation_service.validate(request)

    # Async execution
    import uuid
    val_id = f"val_{uuid.uuid4().hex[:12]}"
    initial_report = ProductionValidationReport(
        validation_id=val_id,
        status="running",
        verdict=ValidationVerdict.PASS,
        started_at=_runtime_service.get_capabilities().model_dump().get("loaded_models", [""])[0],
        provider=request.provider,
        model=request.model or "nano",
        project_id=f"vproj_{val_id}",
    )
    
    def _run_bg():
        _validation_service.validate(request)

    t = threading.Thread(target=_run_bg, daemon=True)
    t.start()
    return initial_report


@router.get("/validations", response_model=list[ProductionValidationReport])
def list_production_validations(limit: int = 20) -> list[ProductionValidationReport]:
    """List recent production validation reports."""
    return _validation_service.list_validations(limit=limit)


@router.get("/validations/{validation_id}", response_model=ProductionValidationReport)
def get_production_validation_status(validation_id: str) -> ProductionValidationReport:
    """Get the current progress and status of a production validation."""
    report = _validation_service.get_validation_report(validation_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Validation '{validation_id}' not found.")
    return report


@router.get("/validations/{validation_id}/report", response_model=ProductionValidationReport)
def get_production_validation_report(validation_id: str) -> ProductionValidationReport:
    """Get the full detailed production validation report."""
    report = _validation_service.get_validation_report(validation_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Validation '{validation_id}' not found.")
    return report


@router.post("/validations/{validation_id}/cancel")
def cancel_production_validation(validation_id: str) -> dict[str, Any]:
    """Cancel an ongoing production validation."""
    success = _validation_service.cancel_validation(validation_id)
    if not success:
        report = _validation_service.get_validation_report(validation_id)
        if not report:
            raise HTTPException(status_code=404, detail=f"Validation '{validation_id}' not found.")
        return {"validation_id": validation_id, "status": report.status, "cancelled": False}
    return {"validation_id": validation_id, "status": "cancelled", "cancelled": True}
