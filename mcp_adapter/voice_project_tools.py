"""MCP Voice Project Tools Adapter (Phase 13).

Provides coarse-grained, agent-friendly Model Context Protocol tools for AI assistants
(Antigravity, Codex) to direct and orchestrate end-to-end voice projects.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from services.voice_project_dependencies import (
    get_voice_project_operation_manager,
    get_voice_project_service,
    get_voice_project_store,
    resolve_server_tts_provider,
)
from services.voice_project_models import (
    BeatNotFoundError,
    InvalidProjectStateError,
    ResourceBlockedError,
    StaleArtifactError,
    VoiceProjectAlreadyExists,
    VoiceProjectNotFound,
)
from services.voice_project_operations import OperationAlreadyRunningError

logger = logging.getLogger(__name__)


def _success_content(data: dict[str, Any]) -> dict:
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


def _error_content(msg: str, error_code: str = "ERROR", project_id: str | None = None, details: dict | None = None) -> dict:
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


def handle_voice_project_tool(
    name: str,
    args: dict[str, Any],
    request_fn: Callable[..., Any] | None = None,
    api_url: str | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> dict | None:
    """Dispatch Voice Project MCP tools."""
    if not name.startswith("chatterbox_voice_"):
        return None

    try:
        service = get_voice_project_service()
        store = get_voice_project_store()
        op_manager = get_voice_project_operation_manager()

        if name == "chatterbox_voice_project_create":
            script_text = args.get("script_text", "")
            if not script_text or not script_text.strip():
                return _error_content("Field 'script_text' cannot be empty.", "VALIDATION_ERROR")

            project_id = args.get("project_id")
            title = args.get("title")
            language = args.get("language", "en")
            config = args.get("config")

            pstate = service.create_project(
                script_text=script_text,
                project_id=project_id,
                title=title,
                language=language,
                config=config,
            )
            summary = service.get_project(pstate.project_id)
            return _success_content(summary.to_dict())

        elif name == "chatterbox_voice_project_get":
            project_id = args.get("project_id")
            if not project_id:
                return _error_content("Field 'project_id' is required.", "VALIDATION_ERROR")
            summary = service.get_project(project_id)
            return _success_content(summary.to_dict())

        elif name == "chatterbox_voice_plan":
            project_id = args.get("project_id")
            if not project_id:
                return _error_content("Field 'project_id' is required.", "VALIDATION_ERROR")
            config = args.get("config")

            op = op_manager.submit(
                project_id=project_id,
                operation="plan",
                task_fn=lambda *a, **kw: service.plan(project_id, config=config),
            )
            return _success_content({
                "job_id": op.id,
                "project_id": project_id,
                "operation": "plan",
                "status": op.status.value,
                "suggested_next_action": f"Call chatterbox_voice_job_status with job_id '{op.id}' to monitor planning.",
            })

        elif name == "chatterbox_voice_check_resources":
            project_id = args.get("project_id")
            if not project_id:
                return _error_content("Field 'project_id' is required.", "VALIDATION_ERROR")
            manifest_path = args.get("manifest_path")

            op = op_manager.submit(
                project_id=project_id,
                operation="check_resources",
                task_fn=lambda *a, **kw: service.check_resources(project_id, manifest_path=manifest_path),
            )
            return _success_content({
                "job_id": op.id,
                "project_id": project_id,
                "operation": "check_resources",
                "status": op.status.value,
                "suggested_next_action": f"Call chatterbox_voice_job_status with job_id '{op.id}' to inspect resource readiness.",
            })

        elif name == "chatterbox_voice_render":
            project_id = args.get("project_id")
            if not project_id:
                return _error_content("Field 'project_id' is required.", "VALIDATION_ERROR")
            provider_name = args.get("provider", "local")
            beats = args.get("beats")
            auto_qc = args.get("auto_qc", True)
            force_rerender = args.get("force_rerender", False)
            allow_blocked = args.get("allow_blocked", False)

            # Pre-validate staleness and blocking state
            is_stale, reason = store.check_staleness(project_id, for_render=True)
            if is_stale:
                return _error_content(f"Cannot render project '{project_id}': {reason}", "STALE_ARTIFACT", project_id=project_id)

            report = store.load_resource_report(project_id)
            if report and report.readiness.render_blocked and not allow_blocked:
                missing_terms = [g.term or g.intent or g.id for g in report.missing if g.priority.value == "required"]
                return _error_content(
                    f"Resource check is BLOCKED. Missing required resources: {', '.join(missing_terms)}",
                    "RESOURCE_BLOCKED",
                    project_id=project_id,
                )

            provider = resolve_server_tts_provider(provider_name)
            svc = get_voice_project_service(store=store, execution_port=provider, provider_name=provider_name)

            def _task(*a, cancellation_token=None, progress_callback=None, **kw):
                return svc.render(
                    project_id=project_id,
                    beats=beats,
                    execution_port=provider,
                    allow_resource_blocked=allow_blocked,
                    force_rerender=force_rerender,
                    auto_qc=auto_qc,
                    progress_callback=progress_callback,
                    cancellation_token=cancellation_token,
                )

            op = op_manager.submit(
                project_id=project_id,
                operation="render",
                task_fn=_task,
            )
            return _success_content({
                "job_id": op.id,
                "project_id": project_id,
                "operation": "render",
                "status": op.status.value,
                "suggested_next_action": f"Call chatterbox_voice_job_status with job_id '{op.id}' to monitor rendering progress.",
            })

        elif name == "chatterbox_voice_render_beat":
            project_id = args.get("project_id")
            beat_id = args.get("beat_id")
            if not project_id or not beat_id:
                return _error_content("Fields 'project_id' and 'beat_id' are required.", "VALIDATION_ERROR")
            provider_name = args.get("provider", "local")
            allow_blocked = args.get("allow_blocked", False)

            plan = store.load_voice_plan(project_id)
            if not plan or not any(b.id == beat_id for b in plan.beats):
                return _error_content(f"Beat '{beat_id}' not found in project '{project_id}'.", "BEAT_NOT_FOUND", project_id=project_id)

            provider = resolve_server_tts_provider(provider_name)
            svc = get_voice_project_service(store=store, execution_port=provider, provider_name=provider_name)

            def _beat_task(*a, cancellation_token=None, progress_callback=None, **kw):
                return svc.render_beat(
                    project_id=project_id,
                    beat_id=beat_id,
                    execution_port=provider,
                    allow_resource_blocked=allow_blocked,
                    progress_callback=progress_callback,
                    cancellation_token=cancellation_token,
                )

            op = op_manager.submit(
                project_id=project_id,
                operation="render_beat",
                task_fn=_beat_task,
            )
            return _success_content({
                "job_id": op.id,
                "project_id": project_id,
                "operation": "render_beat",
                "beat_id": beat_id,
                "status": op.status.value,
            })

        elif name == "chatterbox_voice_qc":
            project_id = args.get("project_id")
            if not project_id:
                return _error_content("Field 'project_id' is required.", "VALIDATION_ERROR")
            beats = args.get("beats")

            op = op_manager.submit(
                project_id=project_id,
                operation="evaluate",
                task_fn=lambda *a, **kw: service.evaluate(project_id, beats=beats),
            )
            return _success_content({
                "job_id": op.id,
                "project_id": project_id,
                "operation": "evaluate",
                "status": op.status.value,
            })

        elif name == "chatterbox_voice_job_status":
            job_id = args.get("job_id")
            if not job_id:
                return _error_content("Field 'job_id' is required.", "VALIDATION_ERROR")
            op = op_manager.get_operation(job_id)
            if not op:
                return _error_content(f"Operation job '{job_id}' not found.", "JOB_NOT_FOUND")
            return _success_content(op.to_dict())

        elif name == "chatterbox_voice_job_cancel":
            job_id = args.get("job_id")
            if not job_id:
                return _error_content("Field 'job_id' is required.", "VALIDATION_ERROR")
            success, msg = op_manager.cancel_operation(job_id)
            if not success:
                return _error_content(msg, "CANCEL_FAILED")
            return _success_content({"job_id": job_id, "cancelled": True, "message": msg})

        return None

    except VoiceProjectNotFound as exc:
        return _error_content(str(exc), "PROJECT_NOT_FOUND", project_id=args.get("project_id"))
    except VoiceProjectAlreadyExists as exc:
        return _error_content(str(exc), "PROJECT_ALREADY_EXISTS", project_id=args.get("project_id"))
    except BeatNotFoundError as exc:
        return _error_content(str(exc), "BEAT_NOT_FOUND", project_id=args.get("project_id"))
    except ResourceBlockedError as exc:
        return _error_content(str(exc), "RESOURCE_BLOCKED", project_id=args.get("project_id"))
    except StaleArtifactError as exc:
        return _error_content(str(exc), "STALE_ARTIFACT", project_id=args.get("project_id"))
    except InvalidProjectStateError as exc:
        return _error_content(str(exc), "INVALID_PROJECT_STATE", project_id=args.get("project_id"))
    except OperationAlreadyRunningError as exc:
        return _error_content(str(exc), "OPERATION_ALREADY_RUNNING", project_id=args.get("project_id"))
    except Exception as exc:
        logger.exception("MCP Tool Execution Error: %s", exc)
        return _error_content(f"Internal MCP Error: {exc}", "INTERNAL_ERROR", project_id=args.get("project_id"))
