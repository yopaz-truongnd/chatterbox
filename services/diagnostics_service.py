"""Diagnostics Bundle Service (Phase 20).

Creates sanitized, comprehensive diagnostic bundles for troubleshooting voice projects
and series without leaking private paths, API keys, or full audio content.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.local_runtime_service import LocalRuntimeService
from services.production_event_models import ProductionErrorCode
from services.production_event_store import get_production_event_store
from services.production_health_service import get_project_health, get_series_health
from services.voice_project_dependencies import (
    get_voice_project_operation_manager,
    get_voice_project_store,
    get_voice_project_workflow_service,
)
from services.voice_series_store import get_voice_series_store


def _sanitize_path(path: str | Path | None) -> str | None:
    """Strip absolute directories, returning only filename or safe relative name."""
    if path is None:
        return None
    p = str(path)
    # Remove common absolute paths
    parts = Path(p).parts
    if len(parts) > 2:
        return str(Path(parts[-2]) / parts[-1])
    return Path(p).name


def _sanitize_dict(data: dict[str, Any] | list[Any] | Any) -> Any:
    """Recursively scrub secrets, absolute paths, and private keys from dictionary."""
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            if any(secret in k_lower for secret in ("key", "secret", "token", "password", "auth")):
                sanitized[k] = "[REDACTED]"
            elif "path" in k_lower or "dir" in k_lower or "file" in k_lower:
                if isinstance(v, str):
                    sanitized[k] = _sanitize_path(v)
                elif isinstance(v, list):
                    sanitized[k] = [_sanitize_path(item) if isinstance(item, str) else _sanitize_dict(item) for item in v]
                else:
                    sanitized[k] = _sanitize_dict(v)
            else:
                sanitized[k] = _sanitize_dict(v)
        return sanitized
    elif isinstance(data, list):
        return [_sanitize_dict(item) for item in data]
    return data


class DiagnosticsService:
    """Service for generating diagnostic packages."""

    def __init__(
        self,
        project_store: Any | None = None,
        series_store: Any | None = None,
        event_store: Any | None = None,
        runtime_service: Any | None = None,
    ) -> None:
        self.project_store = project_store or get_voice_project_store()
        self.series_store = series_store or get_voice_series_store()
        self.event_store = event_store or get_production_event_store()
        self.runtime_service = runtime_service or LocalRuntimeService()

    def create_project_diagnostics(self, project_id: str) -> dict[str, Any]:
        """Build sanitized diagnostic report for a single project."""
        health = get_project_health(project_id, project_store=self.project_store)
        events = self.event_store.load_project_events(project_id, limit=100)
        caps = self.runtime_service.get_capabilities()

        # Project state details
        project_state = None
        if self.project_store.project_exists(project_id):
            state = self.project_store.get_project_state(project_id)
            project_state = state.model_dump(mode="json")

        # Operations
        op_mgr = get_voice_project_operation_manager()
        ops = op_mgr.list_operations(project_id=project_id, limit=10)

        # Artifacts
        artifacts = {}
        if project_state and "artifacts" in project_state:
            artifacts = project_state["artifacts"]

        bundle = {
            "bundle_type": "project",
            "project_id": project_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "health": health.to_dict(),
            "project_state": _sanitize_dict(project_state),
            "operations": [_sanitize_dict(o.model_dump(mode="json")) for o in ops],
            "recent_events": [_sanitize_dict(e) for e in events],
            "runtime_capabilities": caps.model_dump(mode="json"),
            "artifacts_summary": _sanitize_dict(artifacts),
        }
        return _sanitize_dict(bundle)

    def create_series_diagnostics(self, series_id: str) -> dict[str, Any]:
        """Build sanitized diagnostic report for an entire series."""
        health = get_series_health(series_id, series_store=self.series_store)
        events = self.event_store.load_series_events(series_id, limit=100)
        caps = self.runtime_service.get_capabilities()

        series = self.series_store.get_series(series_id)
        episodes = self.series_store.list_episodes(series_id)

        bundle = {
            "bundle_type": "series",
            "series_id": series_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "health": health.to_dict(),
            "series_state": _sanitize_dict(series.to_dict()) if series else None,
            "episodes": [_sanitize_dict(ep.to_dict()) for ep in episodes],
            "recent_events": [_sanitize_dict(e) for e in events],
            "runtime_capabilities": caps.model_dump(mode="json"),
        }
        return _sanitize_dict(bundle)
