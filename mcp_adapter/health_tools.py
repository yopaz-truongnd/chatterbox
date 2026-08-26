"""MCP Observability, Health, Events & Diagnostics Tools Adapter (Phase 20).

Thin protocol adapter for AI agents to inspect health, query event logs,
and generate diagnostics bundles.
"""

from __future__ import annotations

import json
from typing import Any, Callable


def _success(data: Any) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(data, indent=2, ensure_ascii=False)}],
        "isError": False,
    }


def _error(msg: str, code: str = "ERROR") -> dict:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps({"error": {"code": code, "message": msg}}, indent=2),
            }
        ],
        "isError": True,
    }


def handle_voice_health(args: dict[str, Any], request_fn: Callable | None = None) -> dict[str, Any]:
    project_id = args.get("project_id")
    if not project_id:
        return _error("project_id is required", code="INVALID_ARGUMENTS")
    try:
        from services.production_health_service import get_project_health
        health = get_project_health(project_id)
        return _success(health.to_dict())
    except Exception as exc:
        return _error(f"Failed to get health: {exc}", code="HEALTH_CHECK_FAILED")


def handle_voice_events(args: dict[str, Any], request_fn: Callable | None = None) -> dict[str, Any]:
    project_id = args.get("project_id")
    if not project_id:
        return _error("project_id is required", code="INVALID_ARGUMENTS")
    limit = args.get("limit", 100)
    try:
        from services.production_event_store import get_production_event_store
        store = get_production_event_store()
        events = store.load_project_events(project_id, limit=limit)
        return _success(events)
    except Exception as exc:
        return _error(f"Failed to get events: {exc}", code="EVENTS_QUERY_FAILED")


def handle_voice_diagnostics(args: dict[str, Any], request_fn: Callable | None = None) -> dict[str, Any]:
    project_id = args.get("project_id")
    series_id = args.get("series_id")
    if not project_id and not series_id:
        return _error("Either project_id or series_id is required", code="INVALID_ARGUMENTS")
    try:
        from services.diagnostics_service import DiagnosticsService
        service = DiagnosticsService()
        if project_id:
            bundle = service.create_project_diagnostics(project_id)
        else:
            bundle = service.create_series_diagnostics(series_id)
        return _success(bundle)
    except Exception as exc:
        return _error(f"Failed to create diagnostics: {exc}", code="DIAGNOSTICS_FAILED")


def handle_voice_series_health(args: dict[str, Any], request_fn: Callable | None = None) -> dict[str, Any]:
    series_id = args.get("series_id")
    if not series_id:
        return _error("series_id is required", code="INVALID_ARGUMENTS")
    try:
        from services.production_health_service import get_series_health
        health = get_series_health(series_id)
        return _success(health.to_dict())
    except Exception as exc:
        return _error(f"Failed to get series health: {exc}", code="HEALTH_CHECK_FAILED")


def handle_voice_series_events(args: dict[str, Any], request_fn: Callable | None = None) -> dict[str, Any]:
    series_id = args.get("series_id")
    if not series_id:
        return _error("series_id is required", code="INVALID_ARGUMENTS")
    limit = args.get("limit", 100)
    try:
        from services.production_event_store import get_production_event_store
        store = get_production_event_store()
        events = store.load_series_events(series_id, limit=limit)
        return _success(events)
    except Exception as exc:
        return _error(f"Failed to get series events: {exc}", code="EVENTS_QUERY_FAILED")
