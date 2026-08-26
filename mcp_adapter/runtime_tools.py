"""MCP Runtime Capabilities Tools Adapter (Phase 17).

Provides MCP tool for inspecting local runtime capabilities and production preflight.
Thin adapter calling the LocalRuntimeService or REST endpoints.
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


def handle_runtime_capabilities(args: dict[str, Any], request_fn: Callable | None = None) -> dict[str, Any]:
    """Inspect local runtime capabilities (models, device, formats, concurrent capacity)."""
    try:
        from services.local_runtime_service import LocalRuntimeService

        service = LocalRuntimeService()
        caps = service.get_capabilities()
        return _success(caps.model_dump(mode="json"))
    except Exception as exc:
        return _error(f"Failed to inspect runtime capabilities: {exc}", code="RUNTIME_INSPECTION_FAILED")


def handle_runtime_preflight(args: dict[str, Any], request_fn: Callable | None = None) -> dict[str, Any]:
    """Run production preflight validation for a project before execution."""
    project_id = args.get("project_id")
    if not project_id:
        return _error("project_id is required", code="INVALID_ARGUMENTS")

    provider = args.get("provider", "local")
    requested_formats = args.get("requested_formats", ["wav"])

    try:
        from services.local_runtime_service import LocalRuntimeService

        service = LocalRuntimeService()
        issues = service.run_production_preflight(
            project_id=project_id,
            provider=provider,
            requested_formats=requested_formats,
        )
        has_errors = any(i.severity == "error" for i in issues)
        has_warnings = any(i.severity == "warning" for i in issues)
        status = "blocked" if has_errors else ("warning" if has_warnings else "ok")

        result = {
            "project_id": project_id,
            "status": status,
            "passed": not has_errors,
            "issues": [i.model_dump(mode="json") for i in issues],
        }
        return _success(result)
    except Exception as exc:
        return _error(f"Failed to run preflight check: {exc}", code="PREFLIGHT_FAILED")
