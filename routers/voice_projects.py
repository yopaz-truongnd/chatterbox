"""FastAPI REST Router for Voice Projects (Phase 12).

Provides asynchronous, non-blocking HTTP endpoints for VoiceProject lifecycle,
resource gating, per-beat rendering, QC evaluation, and operation tracking.
"""

from __future__ import annotations

import logging
from typing import Any
from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse

from schemas.voice_projects import (
    CheckVoiceResourcesRequest,
    CreateVoiceProjectRequest,
    EvaluateVoiceProjectRequest,
    HumanActionSchema,
    PlanVoiceProjectRequest,
    RenderBeatRequest,
    RenderVoiceProjectRequest,
    UpdateVoiceScriptRequest,
    VoiceProjectBeatsSummary,
    VoiceProjectErrorDetail,
    VoiceProjectErrorResponse,
    VoiceProjectJobResponse,
    VoiceProjectOperationResponse,
    VoiceProjectResourcesSummary,
    VoiceProjectResponse,
)
from services.render_models import ProjectStatus
from services.resource_models import RequirementPriority
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
    VoiceProjectSummary,
)
from services.voice_project_operations import (
    OperationAlreadyRunningError,
    VoiceProjectOperation,
    VoiceProjectOperationManager,
)
from services.voice_renderer import ProviderUnavailableError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice-projects"])


def _format_summary_response(summary: VoiceProjectSummary) -> VoiceProjectResponse:
    """Helper to convert domain VoiceProjectSummary into public schema response."""
    human_action_schema = None
    if summary.human_action:
        human_action_schema = HumanActionSchema(
            action_type=summary.human_action.action_type.value,
            reason=summary.human_action.reason,
            items=summary.human_action.items,
        )

    return VoiceProjectResponse(
        project_id=summary.project_id,
        title=summary.title,
        stage=summary.stage.value,
        language=summary.language,
        beats=VoiceProjectBeatsSummary(
            total=summary.total_beats,
            rendered=summary.rendered_beats,
            passed=summary.passed_beats,
            review=summary.review_beats,
            failed=summary.failed_beats,
        ),
        resources=VoiceProjectResourcesSummary(
            readiness_score=int(summary.resource_readiness_score) if summary.resource_readiness_score is not None else None,
            blocked=summary.resource_blocked,
            required_gaps_count=summary.required_gaps_count,
            recommended_gaps_count=summary.recommended_gaps_count,
        ),
        suggested_action=summary.suggested_action,
        human_action=human_action_schema,
        last_error=summary.last_error,
    )


def _handle_domain_error(exc: Exception, project_id: str | None = None) -> JSONResponse:
    """Format domain exceptions into structured JSON error responses with appropriate HTTP codes."""
    if isinstance(exc, VoiceProjectNotFound):
        status_code = status.HTTP_404_NOT_FOUND
        code = "PROJECT_NOT_FOUND"
    elif isinstance(exc, VoiceProjectAlreadyExists):
        status_code = status.HTTP_409_CONFLICT
        code = "PROJECT_ALREADY_EXISTS"
    elif isinstance(exc, BeatNotFoundError):
        status_code = status.HTTP_404_NOT_FOUND
        code = "BEAT_NOT_FOUND"
    elif isinstance(exc, ResourceBlockedError):
        status_code = status.HTTP_409_CONFLICT
        code = "RESOURCE_BLOCKED"
    elif isinstance(exc, StaleArtifactError):
        status_code = status.HTTP_409_CONFLICT
        code = "STALE_ARTIFACT"
    elif isinstance(exc, InvalidProjectStateError):
        status_code = status.HTTP_409_CONFLICT
        code = "INVALID_PROJECT_STATE"
    elif isinstance(exc, OperationAlreadyRunningError):
        status_code = status.HTTP_409_CONFLICT
        code = "OPERATION_ALREADY_RUNNING"
    elif isinstance(exc, ProviderUnavailableError):
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        code = "PROVIDER_UNAVAILABLE"
    else:
        logger.exception("Unexpected error in voice project endpoint: %s", exc)
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        code = "INTERNAL_SERVER_ERROR"

    err_payload = VoiceProjectErrorResponse(
        error=VoiceProjectErrorDetail(
            code=code,
            message=str(exc),
            project_id=project_id,
        )
    )
    return JSONResponse(status_code=status_code, content=err_payload.model_dump(mode="json"))


# =========================================================
# Project Lifecycle Endpoints
# =========================================================


@router.post(
    "/api/v1/voice-projects",
    response_model=VoiceProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new narration voice project",
)
def create_voice_project(req: CreateVoiceProjectRequest):
    """Initialize a new voice project workspace with source script."""
    service = get_voice_project_service()
    try:
        pstate = service.create_project(
            script_text=req.script_text,
            project_id=req.project_id,
            title=req.title,
            language=req.language,
            config=req.config,
        )
        summary = service.get_project(pstate.project_id)
        return _format_summary_response(summary)
    except Exception as exc:
        return _handle_domain_error(exc, project_id=req.project_id)


@router.get(
    "/api/v1/voice-projects",
    response_model=list[VoiceProjectResponse],
    summary="List all voice projects",
)
def list_voice_projects(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Retrieve summaries of all local voice projects."""
    store = get_voice_project_store()
    service = get_voice_project_service(store=store)

    project_dirs = [p for p in store.root_dir.iterdir() if p.is_dir() and (p / "project.yaml").exists()]
    project_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    results = []
    for p_dir in project_dirs[offset : offset + limit]:
        try:
            summary = service.get_project(p_dir.name)
            results.append(_format_summary_response(summary))
        except Exception:
            continue

    return results


@router.get(
    "/api/v1/voice-projects/{project_id}",
    response_model=VoiceProjectResponse,
    summary="Get project summary and recommended next action",
)
def get_voice_project(project_id: str):
    """Get high-level agent-friendly project summary."""
    service = get_voice_project_service()
    try:
        summary = service.get_project(project_id)
        return _format_summary_response(summary)
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


@router.put(
    "/api/v1/voice-projects/{project_id}/script",
    response_model=VoiceProjectResponse,
    summary="Update project source script",
)
def update_voice_project_script(project_id: str, req: UpdateVoiceScriptRequest):
    """Update project source script, invalidating downstream artifacts."""
    service = get_voice_project_service()
    try:
        service.update_script(project_id, req.script_text)
        summary = service.get_project(project_id)
        return _format_summary_response(summary)
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


# =========================================================
# Planning Endpoints (Async 202)
# =========================================================


@router.post(
    "/api/v1/voice-projects/{project_id}/plan",
    response_model=VoiceProjectOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger async story analysis and voice planning",
)
def plan_voice_project(project_id: str, req: PlanVoiceProjectRequest | None = None):
    """Enqueue background Voice Planning (Story Analysis, Narration Plan, Sound Direction, Critic)."""
    service = get_voice_project_service()
    op_manager = get_voice_project_operation_manager()

    try:
        op = op_manager.submit(
            project_id=project_id,
            operation="plan",
            task_fn=lambda *a, **kw: service.plan(project_id, config=req.config if req else None),
        )
        return VoiceProjectOperationResponse(
            job_id=op.id,
            project_id=project_id,
            operation="plan",
            status=op.status.value,
            message="Planning operation queued successfully.",
        )
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


@router.get(
    "/api/v1/voice-projects/{project_id}/plan",
    summary="Get final reviewed VoicePlan artifact",
)
def get_voice_plan(project_id: str):
    """Retrieve final compiled VoicePlan artifact dictionary."""
    store = get_voice_project_store()
    plan = store.load_voice_plan(project_id)
    if not plan:
        return _handle_domain_error(
            InvalidProjectStateError(f"Project '{project_id}' has no VoicePlan. Run plan first."),
            project_id=project_id,
        )
    return plan.to_dict()


# =========================================================
# Resource Checking Endpoints (Async 202)
# =========================================================


@router.post(
    "/api/v1/voice-projects/{project_id}/resources/check",
    response_model=VoiceProjectOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger async resource readiness check",
)
def check_voice_project_resources(project_id: str, req: CheckVoiceResourcesRequest | None = None):
    """Enqueue background Resource Checking against Asset Library and Pronunciation Knowledge."""
    service = get_voice_project_service()
    op_manager = get_voice_project_operation_manager()

    try:
        manifest_path = req.manifest_path if req else None
        op = op_manager.submit(
            project_id=project_id,
            operation="check_resources",
            task_fn=lambda *a, **kw: service.check_resources(project_id, manifest_path=manifest_path),
        )
        return VoiceProjectOperationResponse(
            job_id=op.id,
            project_id=project_id,
            operation="check_resources",
            status=op.status.value,
            message="Resource check operation queued successfully.",
        )
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


@router.get(
    "/api/v1/voice-projects/{project_id}/resources",
    summary="Get compiled ResourceReport artifact",
)
def get_resource_report(project_id: str):
    """Retrieve compiled ResourceReport artifact dictionary."""
    store = get_voice_project_store()
    report = store.load_resource_report(project_id)
    if not report:
        return _handle_domain_error(
            InvalidProjectStateError(f"Project '{project_id}' has no ResourceReport. Run check_resources first."),
            project_id=project_id,
        )
    return report.to_dict()


@router.get(
    "/api/v1/voice-projects/{project_id}/resources/missing",
    summary="Get missing resource gaps grouped by priority",
)
def get_missing_resources(project_id: str):
    """Retrieve missing required, recommended, and optional resource gaps."""
    store = get_voice_project_store()
    report = store.load_resource_report(project_id)
    if not report:
        return _handle_domain_error(
            InvalidProjectStateError(f"Project '{project_id}' has no ResourceReport. Run check_resources first."),
            project_id=project_id,
        )

    req_gaps = [g.model_dump(mode="json") for g in report.missing if g.priority == RequirementPriority.REQUIRED]
    rec_gaps = [g.model_dump(mode="json") for g in report.missing if g.priority == RequirementPriority.RECOMMENDED]
    opt_gaps = [g.model_dump(mode="json") for g in report.missing if g.priority == RequirementPriority.OPTIONAL]

    return {
        "project_id": project_id,
        "readiness_score": report.readiness.score,
        "render_blocked": report.readiness.render_blocked,
        "required": req_gaps,
        "recommended": rec_gaps,
        "optional": opt_gaps,
    }


# =========================================================
# Render & QC Endpoints (Async 202)
# =========================================================


@router.post(
    "/api/v1/voice-projects/{project_id}/render",
    response_model=VoiceProjectOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger async narration synthesis and voice QC",
)
def render_voice_project(project_id: str, req: RenderVoiceProjectRequest | None = None):
    """Enqueue background narration synthesis and Voice QC."""
    req_model = req or RenderVoiceProjectRequest()
    store = get_voice_project_store()
    op_manager = get_voice_project_operation_manager()

    try:
        # Pre-validate staleness & resource gate before queueing
        is_stale, reason = store.check_staleness(project_id, for_render=True)
        if is_stale:
            raise StaleArtifactError(f"Cannot render project '{project_id}': {reason}")

        report = store.load_resource_report(project_id)
        if report and report.readiness.render_blocked and not req_model.allow_blocked:
            missing_terms = [g.term or g.intent or g.id for g in report.missing if g.priority.value == "required"]
            raise ResourceBlockedError(
                f"Cannot render project '{project_id}': Resource check is BLOCKED. "
                f"Missing required resources: {', '.join(missing_terms)}"
            )

        provider = resolve_server_tts_provider(req_model.provider)
        service = get_voice_project_service(store=store, execution_port=provider, provider_name=req_model.provider)

        def _task(*args, cancellation_token=None, progress_callback=None, **kwargs):
            return service.render(
                project_id=project_id,
                beats=req_model.beats,
                execution_port=provider,
                allow_resource_blocked=req_model.allow_blocked,
                force_rerender=req_model.force_rerender,
                auto_qc=req_model.auto_qc,
                progress_callback=progress_callback,
                cancellation_token=cancellation_token,
            )

        op = op_manager.submit(
            project_id=project_id,
            operation="render",
            task_fn=_task,
        )
        return VoiceProjectOperationResponse(
            job_id=op.id,
            project_id=project_id,
            operation="render",
            status=op.status.value,
            message="Render operation queued successfully.",
        )
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


@router.post(
    "/api/v1/voice-projects/{project_id}/beats/{beat_id}/render",
    response_model=VoiceProjectOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger async selective rendering for a single beat",
)
def render_voice_project_beat(project_id: str, beat_id: str, req: RenderBeatRequest | None = None):
    """Enqueue background selective rendering for a single beat."""
    req_model = req or RenderBeatRequest()
    store = get_voice_project_store()
    op_manager = get_voice_project_operation_manager()

    try:
        plan = store.load_voice_plan(project_id)
        if not plan:
            raise InvalidProjectStateError(f"Project '{project_id}' has no VoicePlan. Run plan first.")

        matching_beat = next((b for b in plan.beats if b.id == beat_id), None)
        if not matching_beat:
            raise BeatNotFoundError(f"Beat '{beat_id}' does not exist in project '{project_id}'.")

        provider = resolve_server_tts_provider(req_model.provider)
        service = get_voice_project_service(store=store, execution_port=provider, provider_name=req_model.provider)

        def _task(*args, cancellation_token=None, progress_callback=None, **kwargs):
            return service.render_beat(
                project_id=project_id,
                beat_id=beat_id,
                execution_port=provider,
                allow_resource_blocked=req_model.allow_blocked,
                progress_callback=progress_callback,
                cancellation_token=cancellation_token,
            )

        op = op_manager.submit(
            project_id=project_id,
            operation="render_beat",
            task_fn=_task,
        )
        return VoiceProjectOperationResponse(
            job_id=op.id,
            project_id=project_id,
            operation="render_beat",
            status=op.status.value,
            message=f"Render beat '{beat_id}' operation queued successfully.",
        )
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


@router.post(
    "/api/v1/voice-projects/{project_id}/evaluate",
    response_model=VoiceProjectOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger async Voice QC re-evaluation without synthesizing audio",
)
def evaluate_voice_project(project_id: str, req: EvaluateVoiceProjectRequest | None = None):
    """Enqueue background Voice QC evaluation on existing renders."""
    req_model = req or EvaluateVoiceProjectRequest()
    service = get_voice_project_service()
    op_manager = get_voice_project_operation_manager()

    try:
        op = op_manager.submit(
            project_id=project_id,
            operation="evaluate",
            task_fn=lambda *a, **kw: service.evaluate(project_id, beats=req_model.beats),
        )
        return VoiceProjectOperationResponse(
            job_id=op.id,
            project_id=project_id,
            operation="evaluate",
            status=op.status.value,
            message="QC evaluation operation queued successfully.",
        )
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


# =========================================================
# Operation Job Status & Cancellation Endpoints
# =========================================================


@router.get(
    "/api/v1/voice-project-jobs/{job_id}",
    response_model=VoiceProjectJobResponse,
    summary="Get background operation job status and progress",
)
def get_voice_project_job(job_id: str):
    """Retrieve detailed status, progress, stage, result, or error of an asynchronous operation."""
    op_manager = get_voice_project_operation_manager()
    op = op_manager.get_operation(job_id)
    if not op:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Operation job '{job_id}' not found.",
        )

    return VoiceProjectJobResponse(
        id=op.id,
        project_id=op.project_id,
        operation=op.operation,
        status=op.status.value,
        stage=op.stage,
        beat_id=op.beat_id,
        child_job_id=op.child_job_id,
        progress_percent=op.progress_percent,
        created_at=op.created_at,
        updated_at=op.updated_at,
        result=op.result,
        error=op.error,
    )


@router.post(
    "/api/v1/voice-project-jobs/{job_id}/cancel",
    summary="Cancel a running or queued background operation",
)
def cancel_voice_project_job(job_id: str):
    """Request cooperative cancellation of a background project operation."""
    op_manager = get_voice_project_operation_manager()
    success, msg = op_manager.cancel_operation(job_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return {"job_id": job_id, "status": "cancelled", "message": msg}
