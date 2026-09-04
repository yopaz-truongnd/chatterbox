"""MCP Runtime Capabilities and Validation Tools Adapter (Phases 17 & 21).

Provides MCP tools for inspecting local runtime capabilities, production preflight,
and launching/monitoring real-runtime production validation.
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
            selected_model=args.get("selected_model"),
            reference_voice=args.get("reference_voice"),
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


# =====================================================================
# Real Production Validation MCP Handlers (Phase 21)
# =====================================================================

def handle_validate_runtime(args: dict[str, Any], request_fn: Callable | None = None) -> dict[str, Any]:
    """Start real-runtime production validation."""
    try:
        from services.production_validation_models import ProductionValidationRequest
        from services.production_validation_service import ProductionValidationService

        req = ProductionValidationRequest(
            validation_profile_id=args.get("profile"),
            script_path=args.get("script_path"),
            script_text=args.get("script_text"),
            provider=args.get("provider", "local"),
            model=args.get("model"),
            language=args.get("language", "en"),
            voice_mode=args.get("voice_mode", "tts"),
            reference_voice=args.get("reference_voice"),
            output_formats=args.get("output_formats", ["wav", "mp3"]),
            require_narration_acceptance=args.get("require_narration_acceptance", True),
            require_final_approval=args.get("require_final_approval", True),
            run_incremental_reproduction=args.get("run_incremental_reproduction", True),
            run_cancellation_tests=args.get("run_cancellation_tests", False),
        )

        service = ProductionValidationService()
        report = service.validate(req)
        return _success(report.model_dump(mode="json"))
    except Exception as exc:
        return _error(f"Failed to run runtime validation: {exc}", code="VALIDATION_FAILED")


def handle_validation_status(args: dict[str, Any], request_fn: Callable | None = None) -> dict[str, Any]:
    """Get production validation progress and status."""
    val_id = args.get("validation_id")
    if not val_id:
        return _error("validation_id is required", code="INVALID_ARGUMENTS")
    try:
        from services.production_validation_service import ProductionValidationService

        service = ProductionValidationService()
        report = service.get_validation_report(val_id)
        if not report:
            return _error(f"Validation '{val_id}' not found", code="NOT_FOUND")
        return _success({
            "validation_id": report.validation_id,
            "status": report.status,
            "verdict": report.verdict.value,
            "beat_count": report.beat_count,
            "qc_pass_count": report.qc_pass_count,
            "qc_review_count": report.qc_review_count,
            "qc_failed_count": report.qc_failed_count,
            "total_duration_ms": report.total_duration_ms,
            "completed_at": report.completed_at,
        })
    except Exception as exc:
        return _error(f"Failed to get validation status: {exc}", code="STATUS_FAILED")


def handle_validation_report(args: dict[str, Any], request_fn: Callable | None = None) -> dict[str, Any]:
    """Get full production validation report."""
    val_id = args.get("validation_id")
    if not val_id:
        return _error("validation_id is required", code="INVALID_ARGUMENTS")
    try:
        from services.production_validation_service import ProductionValidationService

        service = ProductionValidationService()
        report = service.get_validation_report(val_id)
        if not report:
            return _error(f"Validation '{val_id}' not found", code="NOT_FOUND")
        return _success(report.model_dump(mode="json"))
    except Exception as exc:
        return _error(f"Failed to get validation report: {exc}", code="REPORT_FAILED")


def handle_validation_cancel(args: dict[str, Any], request_fn: Callable | None = None) -> dict[str, Any]:
    """Cancel a running production validation."""
    val_id = args.get("validation_id")
    if not val_id:
        return _error("validation_id is required", code="INVALID_ARGUMENTS")
    try:
        from services.production_validation_service import ProductionValidationService

        service = ProductionValidationService()
        cancelled = service.cancel_validation(val_id)
        return _success({"validation_id": val_id, "cancelled": cancelled})
    except Exception as exc:
        return _error(f"Failed to cancel validation: {exc}", code="CANCEL_FAILED")
