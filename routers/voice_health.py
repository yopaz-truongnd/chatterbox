"""FastAPI REST Router for Observability, Health, Events & Diagnostics (Phase 20).

Provides monitoring and diagnostic endpoints for projects and series.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, HTTPException, Query

from services.diagnostics_service import DiagnosticsService
from services.production_event_models import (
    ProjectProductionHealth,
    SeriesProductionHealth,
)
from services.production_event_store import get_production_event_store
from services.production_health_service import get_project_health, get_series_health
from services.voice_project_models import VoiceProjectNotFound
from services.voice_project_dependencies import (
    get_voice_project_operation_manager,
    get_voice_project_store,
    get_voice_project_workflow_service,
)
from services.voice_series_store import get_voice_series_store

router = APIRouter(prefix="/api/v1", tags=["voice-observability"])

_event_store = get_production_event_store()
_diag_service = DiagnosticsService()


# ==========================================
# 1. Project Health & Observability
# ==========================================


@router.get("/voice-projects/{project_id}/health", response_model=ProjectProductionHealth)
def get_voice_project_health(project_id: str) -> ProjectProductionHealth:
    return get_project_health(
        project_id,
        project_store=get_voice_project_store(),
        operation_manager=get_voice_project_operation_manager(),
        workflow_service=get_voice_project_workflow_service(),
    )


@router.get("/voice-projects/{project_id}/events")
def get_voice_project_events(
    project_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[dict[str, Any]]:
    return _event_store.load_project_events(project_id, limit=limit)


@router.post("/voice-projects/{project_id}/diagnostics")
def create_voice_project_diagnostics(project_id: str) -> dict[str, Any]:
    return _diag_service.create_project_diagnostics(project_id)


# ==========================================
# 2. Series Health & Observability
# ==========================================


@router.get("/voice-series/{series_id}/health", response_model=SeriesProductionHealth)
def get_voice_series_health(series_id: str) -> SeriesProductionHealth:
    return get_series_health(
        series_id,
        project_store=get_voice_project_store(),
        series_store=get_voice_series_store(),
    )


@router.get("/voice-series/{series_id}/events")
def get_voice_series_events(
    series_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[dict[str, Any]]:
    return _event_store.load_series_events(series_id, limit=limit)


@router.post("/voice-series/{series_id}/diagnostics")
def create_voice_series_diagnostics(series_id: str) -> dict[str, Any]:
    return _diag_service.create_series_diagnostics(series_id)
