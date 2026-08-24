"""MCP Voice Project Tools Adapter (Phase 13-15).

Provides coarse-grained Model Context Protocol tools for AI Director/Orchestrator agents.
Routes requests cleanly through the FastAPI REST API layer via injected request_fn,
strictly decoupling the external MCP stdio process from server-internal singletons.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _success_content(data: dict[str, Any] | list[Any]) -> dict:
    """Format successful tool execution result into standard MCP content envelope."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(data, indent=2, ensure_ascii=False),
            }
        ],
        "isError": False,
    }


def _error_content(
    msg: str,
    error_code: str = "ERROR",
    project_id: str | None = None,
    details: dict | None = None,
) -> dict:
    """Format error execution result into standard MCP content envelope."""
    err_dict = {
        "error": {
            "code": error_code,
            "message": msg,
            "project_id": project_id,
            "details": details or {},
        }
    }
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(err_dict, indent=2, ensure_ascii=False),
            }
        ],
        "isError": True,
    }


def _execute_rest_request(
    request_fn: Callable[..., Any] | None,
    method: str,
    path: str,
    data: dict[str, Any] | None = None,
) -> dict:
    """Execute HTTP request via provided request_fn or in-process TestClient fallback."""
    if request_fn is not None:
        return request_fn(path, method=method, data=data)

    # In-process TestClient fallback for standalone tests
    try:
        from fastapi.testclient import TestClient
        import api_app

        client = TestClient(api_app.app)
        api_key = os.getenv("CHATTERBOX_API_KEY")
        headers = {"X-API-Key": api_key} if api_key else {}

        if method == "GET":
            resp = client.get(path, headers=headers)
        elif method == "POST":
            resp = client.post(path, json=data or {}, headers=headers)
        elif method == "PUT":
            resp = client.put(path, json=data or {}, headers=headers)
        else:
            resp = client.request(method, path, json=data, headers=headers)

        try:
            return resp.json()
        except Exception:
            return {"detail": resp.text, "status_code": resp.status_code}
    except Exception as exc:
        return {"detail": f"Failed to execute local request: {str(exc)}"}


def _handle_response(res: dict, project_id: str | None = None) -> dict:
    """Safely inspect and format REST response dictionary into MCP envelope."""
    if res.get("error"):
        err = res["error"]
        msg = err.get("message", "Error") if isinstance(err, dict) else str(err)
        code = err.get("code", "ERROR") if isinstance(err, dict) else "ERROR"
        return _error_content(msg, error_code=code, project_id=project_id)
    if "detail" in res and not res.get("id"):
        return _error_content(str(res["detail"]), project_id=project_id)
    return _success_content(res)


def handle_voice_project_tool(
    name: str,
    args: dict[str, Any],
    request_fn: Callable[..., Any] | None = None,
    api_url: str | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> dict | None:
    """Dispatch Voice Project & Workflow MCP tools to REST API."""
    if not name.startswith("chatterbox_voice_"):
        return None

    # 1. Project Creation & Summary
    if name == "chatterbox_voice_project_create":
        script_text = args.get("script_text", "").strip()
        if not script_text:
            return _error_content("Field 'script_text' must not be empty.", error_code="VALIDATION_ERROR")
        res = _execute_rest_request(request_fn, "POST", "/api/v1/voice-projects", data=args)
        return _handle_response(res)

    elif name == "chatterbox_voice_project_get":
        project_id = args.get("project_id", "").strip()
        if not project_id:
            return _error_content("Field 'project_id' is required.", error_code="VALIDATION_ERROR")
        res = _execute_rest_request(request_fn, "GET", f"/api/v1/voice-projects/{project_id}")
        return _handle_response(res, project_id=project_id)

    # 2. Planning & Resources
    elif name == "chatterbox_voice_plan":
        project_id = args.get("project_id", "").strip()
        if not project_id:
            return _error_content("Field 'project_id' is required.", error_code="VALIDATION_ERROR")
        res = _execute_rest_request(request_fn, "POST", f"/api/v1/voice-projects/{project_id}/plan", data=args)
        return _handle_response(res, project_id=project_id)

    elif name == "chatterbox_voice_check_resources":
        project_id = args.get("project_id", "").strip()
        if not project_id:
            return _error_content("Field 'project_id' is required.", error_code="VALIDATION_ERROR")
        res = _execute_rest_request(request_fn, "POST", f"/api/v1/voice-projects/{project_id}/resources/check", data=args)
        return _handle_response(res, project_id=project_id)

    # 3. Narration Render & QC
    elif name == "chatterbox_voice_render":
        project_id = args.get("project_id", "").strip()
        if not project_id:
            return _error_content("Field 'project_id' is required.", error_code="VALIDATION_ERROR")
        res = _execute_rest_request(request_fn, "POST", f"/api/v1/voice-projects/{project_id}/render", data=args)
        return _handle_response(res, project_id=project_id)

    elif name == "chatterbox_voice_render_beat":
        project_id = args.get("project_id", "").strip()
        beat_id = args.get("beat_id", "").strip()
        if not project_id or not beat_id:
            return _error_content("Fields 'project_id' and 'beat_id' are required.", error_code="VALIDATION_ERROR")
        res = _execute_rest_request(request_fn, "POST", f"/api/v1/voice-projects/{project_id}/beats/{beat_id}/render", data=args)
        return _handle_response(res, project_id=project_id)

    elif name == "chatterbox_voice_qc":
        project_id = args.get("project_id", "").strip()
        if not project_id:
            return _error_content("Field 'project_id' is required.", error_code="VALIDATION_ERROR")
        res = _execute_rest_request(request_fn, "POST", f"/api/v1/voice-projects/{project_id}/evaluate", data=args)
        return _handle_response(res, project_id=project_id)

    # 4. Phase 14: Mixing, Mastering & Export
    elif name == "chatterbox_voice_prepare_mix":
        project_id = args.get("project_id", "").strip()
        if not project_id:
            return _error_content("Field 'project_id' is required.", error_code="VALIDATION_ERROR")
        res = _execute_rest_request(request_fn, "POST", f"/api/v1/voice-projects/{project_id}/mix/prepare", data=args)
        return _handle_response(res, project_id=project_id)

    elif name == "chatterbox_voice_mix":
        project_id = args.get("project_id", "").strip()
        if not project_id:
            return _error_content("Field 'project_id' is required.", error_code="VALIDATION_ERROR")
        res = _execute_rest_request(request_fn, "POST", f"/api/v1/voice-projects/{project_id}/mix", data=args)
        return _handle_response(res, project_id=project_id)

    elif name == "chatterbox_voice_master":
        project_id = args.get("project_id", "").strip()
        if not project_id:
            return _error_content("Field 'project_id' is required.", error_code="VALIDATION_ERROR")
        res = _execute_rest_request(request_fn, "POST", f"/api/v1/voice-projects/{project_id}/master", data=args)
        return _handle_response(res, project_id=project_id)

    elif name == "chatterbox_voice_export":
        project_id = args.get("project_id", "").strip()
        if not project_id:
            return _error_content("Field 'project_id' is required.", error_code="VALIDATION_ERROR")
        res = _execute_rest_request(request_fn, "POST", f"/api/v1/voice-projects/{project_id}/export", data=args)
        return _handle_response(res, project_id=project_id)

    elif name == "chatterbox_voice_finalize":
        project_id = args.get("project_id", "").strip()
        if not project_id:
            return _error_content("Field 'project_id' is required.", error_code="VALIDATION_ERROR")
        res = _execute_rest_request(request_fn, "POST", f"/api/v1/voice-projects/{project_id}/finalize", data=args)
        return _handle_response(res, project_id=project_id)

    elif name == "chatterbox_voice_artifacts":
        project_id = args.get("project_id", "").strip()
        if not project_id:
            return _error_content("Field 'project_id' is required.", error_code="VALIDATION_ERROR")
        res = _execute_rest_request(request_fn, "GET", f"/api/v1/voice-projects/{project_id}/artifacts")
        return _handle_response(res, project_id=project_id)

    # 5. Operation Job Tracking & Cancellation
    elif name == "chatterbox_voice_job_status":
        job_id = args.get("job_id", "").strip()
        if not job_id:
            return _error_content("Field 'job_id' is required.", error_code="VALIDATION_ERROR")
        res = _execute_rest_request(request_fn, "GET", f"/api/v1/voice-project-jobs/{job_id}")
        return _handle_response(res)

    elif name == "chatterbox_voice_job_cancel":
        job_id = args.get("job_id", "").strip()
        if not job_id:
            return _error_content("Field 'job_id' is required.", error_code="VALIDATION_ERROR")
        res = _execute_rest_request(request_fn, "POST", f"/api/v1/voice-project-jobs/{job_id}/cancel")
        return _handle_response(res)

    # 6. Phase 15: Autonomous Workflow Orchestration
    elif name == "chatterbox_voice_produce":
        script_text = args.get("script_text", "").strip()
        if not script_text:
            return _error_content("Field 'script_text' is required.", error_code="VALIDATION_ERROR")
        payload = dict(args)
        policy_fields = {
            "provider", "retry_budget", "auto_accept_qc_pass", "allow_resource_substitute",
            "mixing_profile", "mastering_profile", "output_formats", "require_final_approval",
        }
        policy = dict(payload.pop("policy", {}) or {})
        for field in policy_fields:
            if field in payload:
                policy[field] = payload.pop(field)
        payload["policy"] = policy
        res = _execute_rest_request(request_fn, "POST", "/api/v1/voice-workflows", data=payload)
        return _handle_response(res)

    elif name == "chatterbox_voice_workflow_status":
        workflow_id = args.get("workflow_id", "").strip()
        if not workflow_id:
            return _error_content("Field 'workflow_id' is required.", error_code="VALIDATION_ERROR")
        res = _execute_rest_request(request_fn, "GET", f"/api/v1/voice-workflows/{workflow_id}")
        return _handle_response(res)

    elif name == "chatterbox_voice_workflow_resume":
        workflow_id = args.get("workflow_id", "").strip()
        if not workflow_id:
            return _error_content("Field 'workflow_id' is required.", error_code="VALIDATION_ERROR")
        res = _execute_rest_request(request_fn, "POST", f"/api/v1/voice-workflows/{workflow_id}/resume")
        return _handle_response(res)

    elif name == "chatterbox_voice_workflow_approve":
        workflow_id = args.get("workflow_id", "").strip()
        if not workflow_id:
            return _error_content("Field 'workflow_id' is required.", error_code="VALIDATION_ERROR")
        payload = {
            key: args.get(key)
            for key in ("action", "approved", "artifact_id", "artifact_sha256")
            if key in args
        }
        res = _execute_rest_request(
            request_fn,
            "POST",
            f"/api/v1/voice-workflows/{workflow_id}/approve",
            data=payload,
        )
        return _handle_response(res)

    elif name == "chatterbox_voice_workflow_cancel":
        workflow_id = args.get("workflow_id", "").strip()
        if not workflow_id:
            return _error_content("Field 'workflow_id' is required.", error_code="VALIDATION_ERROR")
        res = _execute_rest_request(request_fn, "POST", f"/api/v1/voice-workflows/{workflow_id}/cancel")
        return _handle_response(res)

    return None
