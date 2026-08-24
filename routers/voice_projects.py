"""FastAPI REST Router for Voice Projects (Phase 12-14).

Provides asynchronous, non-blocking HTTP endpoints for VoiceProject lifecycle,
resource gating, per-beat rendering, QC evaluation, mixing, mastering, export,
and operation tracking.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any
from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import FileResponse, JSONResponse

from schemas.voice_projects import (
    ArtifactInfo,
    CheckVoiceResourcesRequest,
    CreateVoiceProjectRequest,
    EvaluateVoiceProjectRequest,
    ExportVoiceProjectRequest,
    FinalizeVoiceProjectRequest,
    HumanActionSchema,
    MasterVoiceProjectRequest,
    MixVoiceProjectRequest,
    PlanVoiceProjectRequest,
    PrepareMixRequest,
    RenderBeatRequest,
    RenderVoiceProjectRequest,
    UpdateVoiceScriptRequest,
    VoiceProjectArtifactsListResponse,
    VoiceProjectBeatsSummary,
    VoiceProjectErrorDetail,
    VoiceProjectErrorResponse,
    VoiceProjectJobResponse,
    VoiceProjectOperationResponse,
    VoiceProjectResourcesSummary,
    VoiceProjectResponse,
)
from services.audio_mix_models import MixPlan
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
from services.voice_project_preflight import VoiceProjectPreflight
from services.voice_renderer import ProviderUnavailableError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice-projects"])


def _format_summary_response(summary: VoiceProjectSummary) -> VoiceProjectResponse:
    """Transform domain VoiceProjectSummary into public schema response."""
    human_schema = None
    if summary.human_action:
        human_schema = HumanActionSchema(
            action_type=summary.human_action.action_type.value
            if hasattr(summary.human_action.action_type, "value")
            else str(summary.human_action.action_type),
            reason=summary.human_action.reason,
            items=summary.human_action.items,
            available_options=getattr(summary.human_action, "available_options", []),
            resume_action=getattr(summary.human_action, "resume_action", None),
        )

    return VoiceProjectResponse(
        project_id=summary.project_id,
        title=summary.title,
        stage=summary.stage.value if hasattr(summary.stage, "value") else str(summary.stage),
        language=summary.language,
        beats=VoiceProjectBeatsSummary(
            total=summary.total_beats,
            rendered=summary.rendered_beats,
            passed=summary.passed_beats,
            review=summary.review_beats,
            failed=summary.failed_beats,
        ),
        resources=VoiceProjectResourcesSummary(
            readiness_score=int(summary.resource_readiness_score * 100)
            if summary.resource_readiness_score is not None
            else None,
            blocked=summary.resource_blocked,
            required_gaps_count=summary.required_gaps_count,
            recommended_gaps_count=summary.recommended_gaps_count,
        ),
        suggested_action=summary.suggested_action,
        human_action=human_schema,
        last_error=summary.last_error,
    )


def _handle_domain_error(exc: Exception, project_id: str | None = None) -> JSONResponse:
    """Map domain exceptions to standard structured HTTP error responses."""
    logger.warning("VoiceProject domain error: %s (%s)", type(exc).__name__, exc)

    if isinstance(exc, VoiceProjectNotFound):
        status_code = status.HTTP_404_NOT_FOUND
        error_code = "PROJECT_NOT_FOUND"
    elif isinstance(exc, BeatNotFoundError):
        status_code = status.HTTP_404_NOT_FOUND
        error_code = "BEAT_NOT_FOUND"
    elif isinstance(exc, VoiceProjectAlreadyExists):
        status_code = status.HTTP_409_CONFLICT
        error_code = "PROJECT_ALREADY_EXISTS"
    elif isinstance(exc, InvalidProjectStateError):
        status_code = status.HTTP_409_CONFLICT
        error_code = "INVALID_PROJECT_STATE"
    elif isinstance(exc, StaleArtifactError):
        status_code = status.HTTP_409_CONFLICT
        error_code = "STALE_ARTIFACT"
    elif isinstance(exc, ResourceBlockedError):
        status_code = status.HTTP_409_CONFLICT
        error_code = "RESOURCE_BLOCKED"
    elif isinstance(exc, OperationAlreadyRunningError):
        status_code = status.HTTP_409_CONFLICT
        error_code = "OPERATION_ALREADY_RUNNING"
    elif isinstance(exc, ProviderUnavailableError):
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        error_code = "PROVIDER_UNAVAILABLE"
    else:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        error_code = "INTERNAL_ERROR"

    err_detail = VoiceProjectErrorDetail(
        code=error_code,
        message=str(exc),
        project_id=project_id,
    )
    envelope = VoiceProjectErrorResponse(error=err_detail)
    return JSONResponse(status_code=status_code, content=envelope.model_dump())


# =========================================================
# 1. Project Management Endpoints (CRUD)
# =========================================================


@router.post(
    "/api/v1/voice-projects",
    response_model=VoiceProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Voice Project",
)
def create_voice_project(req: CreateVoiceProjectRequest):
    """Create a new narration voice project workspace with source script."""
    service = get_voice_project_service()
    try:
        service.create_project(
            script_text=req.script_text,
            project_id=req.project_id,
            title=req.title,
            language=req.language,
            config=req.config,
        )
        # Fetch summary of newly created project
        summary = service.get_project(req.project_id or "latest")
        return _format_summary_response(summary)
    except Exception as exc:
        return _handle_domain_error(exc, project_id=req.project_id)


@router.get(
    "/api/v1/voice-projects",
    response_model=list[VoiceProjectResponse],
    summary="List Voice Projects",
)
def list_voice_projects(
    limit: int = Query(default=50, ge=1, le=200),
    language: str | None = Query(default=None),
    stage: str | None = Query(default=None),
):
    """List all managed voice projects with agent-friendly state summaries."""
    store = get_voice_project_store()
    service = get_voice_project_service(store=store)
    summaries = []

    for proj_id in store.list_projects():
        try:
            summ = service.get_project(proj_id)
            if language and summ.language != language:
                continue
            if stage and summ.stage.value != stage and str(summ.stage) != stage:
                continue
            summaries.append(_format_summary_response(summ))
            if len(summaries) >= limit:
                break
        except Exception as e:
            logger.warning("Failed to load project '%s' in list: %s", proj_id, e)

    return summaries


@router.get(
    "/api/v1/voice-projects/{project_id}",
    response_model=VoiceProjectResponse,
    summary="Get Voice Project Summary",
)
def get_voice_project(project_id: str):
    """Retrieve structured summary, readiness score, and suggested action for a project."""
    service = get_voice_project_service()
    try:
        summary = service.get_project(project_id)
        return _format_summary_response(summary)
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


@router.put(
    "/api/v1/voice-projects/{project_id}/script",
    response_model=VoiceProjectResponse,
    summary="Update Source Script",
)
def update_voice_script(project_id: str, req: UpdateVoiceScriptRequest):
    """Update source script text, safely invalidating downstream plans."""
    service = get_voice_project_service()
    try:
        service.update_script(project_id=project_id, new_script_text=req.script_text)
        summary = service.get_project(project_id)
        return _format_summary_response(summary)
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


# =========================================================
# 2. Asynchronous Operations Endpoints (202 Accepted)
# =========================================================


@router.post(
    "/api/v1/voice-projects/{project_id}/plan",
    response_model=VoiceProjectOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger Voice Planning",
)
def trigger_voice_plan(project_id: str, req: PlanVoiceProjectRequest | None = None):
    """Trigger background story analysis, narration segmentation, and sound direction."""
    store = get_voice_project_store()
    preflight = VoiceProjectPreflight(store=store)

    try:
        preflight.validate_plan_request(project_id)
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)

    op_mgr = get_voice_project_operation_manager()
    service = get_voice_project_service(store=store)
    cfg = req.config if req else None

    try:
        op = op_mgr.submit(
            project_id,
            "plan",
            service.plan,
            project_id,
            config=cfg,
        )
        return VoiceProjectOperationResponse(
            job_id=op.id,
            project_id=project_id,
            operation=op.operation,
            status=op.status.value,
            message="Planning task scheduled successfully",
        )
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


@router.get(
    "/api/v1/voice-projects/{project_id}/plan",
    summary="Get VoicePlan Artifact",
)
def get_voice_plan(project_id: str):
    """Retrieve compiled VoicePlan JSON/YAML artifact."""
    store = get_voice_project_store()
    try:
        if not store.project_exists(project_id):
            raise VoiceProjectNotFound(f"Project '{project_id}' not found.")
        plan = store.load_voice_plan(project_id)
        if not plan:
            raise InvalidProjectStateError(f"Project '{project_id}' has not been planned yet. Run POST /plan first.")
        return plan.to_dict()
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


@router.post(
    "/api/v1/voice-projects/{project_id}/resources/check",
    response_model=VoiceProjectOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger Resource & Pronunciation Check",
)
def trigger_resource_check(project_id: str, req: CheckVoiceResourcesRequest | None = None):
    """Trigger background resource evaluation and pronunciation verification."""
    store = get_voice_project_store()
    preflight = VoiceProjectPreflight(store=store)

    try:
        preflight.validate_resource_check_request(project_id)
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)

    op_mgr = get_voice_project_operation_manager()
    service = get_voice_project_service(store=store)
    manifest_path = req.manifest_path if req else None

    try:
        op = op_mgr.submit(
            project_id,
            "check_resources",
            service.check_resources,
            project_id,
            manifest_path=manifest_path,
        )
        return VoiceProjectOperationResponse(
            job_id=op.id,
            project_id=project_id,
            operation=op.operation,
            status=op.status.value,
            message="Resource check task scheduled successfully",
        )
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


@router.get(
    "/api/v1/voice-projects/{project_id}/resources",
    summary="Get Resource Report",
)
def get_resource_report(project_id: str):
    """Retrieve full ResourceReport artifact."""
    store = get_voice_project_store()
    try:
        if not store.project_exists(project_id):
            raise VoiceProjectNotFound(f"Project '{project_id}' not found.")
        report = store.load_resource_report(project_id)
        if not report:
            raise InvalidProjectStateError(f"Resource report missing for project '{project_id}'. Run POST /resources/check first.")
        return report.to_dict()
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


@router.get(
    "/api/v1/voice-projects/{project_id}/resources/missing",
    summary="Get Missing Resource Gaps",
)
def get_missing_resources(project_id: str):
    """Retrieve categorized missing resource gaps."""
    store = get_voice_project_store()
    try:
        if not store.project_exists(project_id):
            raise VoiceProjectNotFound(f"Project '{project_id}' not found.")
        report = store.load_resource_report(project_id)
        if not report:
            raise InvalidProjectStateError(f"Resource report missing for project '{project_id}'. Run check_resources first.")

        req_gaps = [g.to_dict() for g in report.missing if g.priority == RequirementPriority.REQUIRED]
        rec_gaps = [g.to_dict() for g in report.missing if g.priority == RequirementPriority.RECOMMENDED]

        return {
            "project_id": project_id,
            "render_blocked": report.readiness.render_blocked,
            "readiness_score": report.readiness.score,
            "required": req_gaps,
            "recommended": rec_gaps,
        }
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


@router.post(
    "/api/v1/voice-projects/{project_id}/render",
    response_model=VoiceProjectOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger Full Narration Render",
)
def trigger_render(project_id: str, req: RenderVoiceProjectRequest | None = None):
    """Trigger background synthesis and QC for project narration beats."""
    store = get_voice_project_store()
    preflight = VoiceProjectPreflight(store=store)
    provider_name = req.provider if req else "local"
    beats = req.beats if req else None

    try:
        preflight.validate_render_request(project_id=project_id, provider_name=provider_name, beats=beats)
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)

    op_mgr = get_voice_project_operation_manager()

    try:
        port = resolve_server_tts_provider(provider_name)
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)

    service = get_voice_project_service(store=store, execution_port=port, provider_name=provider_name)
    auto_qc = req.auto_qc if req else True
    force = req.force_rerender if req else False

    try:
        op = op_mgr.submit(
            project_id,
            "render",
            service.render,
            project_id,
            beats=beats,
            auto_qc=auto_qc,
            force_rerender=force,
            allow_resource_blocked=False,  # Strict: no public bypass
        )
        return VoiceProjectOperationResponse(
            job_id=op.id,
            project_id=project_id,
            operation=op.operation,
            status=op.status.value,
            message="Render operation scheduled successfully",
        )
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


@router.post(
    "/api/v1/voice-projects/{project_id}/beats/{beat_id}/render",
    response_model=VoiceProjectOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger Single Beat Render",
)
def trigger_render_beat(project_id: str, beat_id: str, req: RenderBeatRequest | None = None):
    """Trigger background synthesis and QC for a single specific beat."""
    store = get_voice_project_store()
    preflight = VoiceProjectPreflight(store=store)
    provider_name = req.provider if req else "local"

    try:
        preflight.validate_beat_render_request(project_id=project_id, beat_id=beat_id, provider_name=provider_name)
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)

    op_mgr = get_voice_project_operation_manager()

    try:
        port = resolve_server_tts_provider(provider_name)
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)

    service = get_voice_project_service(store=store, execution_port=port, provider_name=provider_name)

    try:
        op = op_mgr.submit(
            project_id,
            f"render_beat_{beat_id}",
            service.render_beat,
            project_id,
            beat_id,
            allow_resource_blocked=False,  # Strict: no public bypass
        )
        return VoiceProjectOperationResponse(
            job_id=op.id,
            project_id=project_id,
            operation=op.operation,
            status=op.status.value,
            message=f"Beat '{beat_id}' render scheduled successfully",
        )
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


@router.post(
    "/api/v1/voice-projects/{project_id}/evaluate",
    response_model=VoiceProjectOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger Voice QC Re-evaluation",
)
def trigger_evaluate(project_id: str, req: EvaluateVoiceProjectRequest | None = None):
    """Trigger background Voice QC evaluation on existing audio attempts."""
    store = get_voice_project_store()
    preflight = VoiceProjectPreflight(store=store)
    beats = req.beats if req else None

    try:
        preflight.validate_evaluate_request(project_id=project_id, beats=beats)
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)

    op_mgr = get_voice_project_operation_manager()
    service = get_voice_project_service(store=store)

    try:
        op = op_mgr.submit(
            project_id,
            "evaluate",
            service.evaluate,
            project_id,
            beats=beats,
        )
        return VoiceProjectOperationResponse(
            job_id=op.id,
            project_id=project_id,
            operation=op.operation,
            status=op.status.value,
            message="QC evaluation task scheduled successfully",
        )
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


# =========================================================
# 3. Phase 14 Post-Production Endpoints (Mix, Master, Export)
# =========================================================


@router.post(
    "/api/v1/voice-projects/{project_id}/mix/prepare",
    response_model=VoiceProjectOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Prepare MixPlan",
)
def trigger_prepare_mix(project_id: str, req: PrepareMixRequest | None = None):
    """Trigger background construction of multi-track MixPlan."""
    store = get_voice_project_store()
    preflight = VoiceProjectPreflight(store=store)
    try:
        preflight.validate_project_exists(project_id)
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)

    op_mgr = get_voice_project_operation_manager()
    service = get_voice_project_service(store=store)
    m_prof = req.mastering_profile if req else "storytelling"
    fmts = req.output_formats if req else ["wav"]
    m_cfg = req.mix_config if req else None

    try:
        op = op_mgr.submit(
            project_id,
            "prepare_mix",
            service.prepare_for_mix,
            project_id,
            mix_config=m_cfg,
            mastering_profile=m_prof,
            output_formats=fmts,
        )
        return VoiceProjectOperationResponse(
            job_id=op.id,
            project_id=project_id,
            operation=op.operation,
            status=op.status.value,
            message="Prepare mix task scheduled successfully",
        )
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


@router.get(
    "/api/v1/voice-projects/{project_id}/mix-plan",
    summary="Get MixPlan Artifact",
)
def get_mix_plan(project_id: str):
    """Retrieve constructed MixPlan artifact."""
    store = get_voice_project_store()
    try:
        if not store.project_exists(project_id):
            raise VoiceProjectNotFound(f"Project '{project_id}' not found.")
        proj_dir = store.get_project_dir(project_id)
        plan_file = proj_dir / "mix-plan.yaml"
        if not plan_file.exists():
            raise InvalidProjectStateError("MixPlan has not been prepared yet. Run POST /mix/prepare first.")
        with open(plan_file, "r", encoding="utf-8") as f:
            plan = MixPlan.from_yaml(f.read())
        return plan.to_dict()
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


@router.post(
    "/api/v1/voice-projects/{project_id}/mix",
    response_model=VoiceProjectOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger Multi-track Audio Mix",
)
def trigger_mix(project_id: str, req: MixVoiceProjectRequest | None = None):
    """Trigger background rendering of multi-track audio mix."""
    store = get_voice_project_store()
    preflight = VoiceProjectPreflight(store=store)
    try:
        preflight.validate_project_exists(project_id)
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)

    op_mgr = get_voice_project_operation_manager()
    service = get_voice_project_service(store=store)
    m_cfg = req.mix_config if req else None

    try:
        op = op_mgr.submit(
            project_id,
            "mix",
            service.mix,
            project_id,
            mix_config=m_cfg,
        )
        return VoiceProjectOperationResponse(
            job_id=op.id,
            project_id=project_id,
            operation=op.operation,
            status=op.status.value,
            message="Audio mix task scheduled successfully",
        )
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


@router.post(
    "/api/v1/voice-projects/{project_id}/master",
    response_model=VoiceProjectOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger Audio Mastering",
)
def trigger_master(project_id: str, req: MasterVoiceProjectRequest | None = None):
    """Trigger background audio mastering and loudness normalization."""
    store = get_voice_project_store()
    preflight = VoiceProjectPreflight(store=store)
    try:
        preflight.validate_project_exists(project_id)
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)

    op_mgr = get_voice_project_operation_manager()
    service = get_voice_project_service(store=store)
    prof = req.profile if req else "storytelling"

    try:
        op = op_mgr.submit(
            project_id,
            "master",
            service.master,
            project_id,
            profile_name=prof,
        )
        return VoiceProjectOperationResponse(
            job_id=op.id,
            project_id=project_id,
            operation=op.operation,
            status=op.status.value,
            message="Audio mastering task scheduled successfully",
        )
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


@router.post(
    "/api/v1/voice-projects/{project_id}/export",
    response_model=VoiceProjectOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger Audio Deliverables Export",
)
def trigger_export(project_id: str, req: ExportVoiceProjectRequest | None = None):
    """Trigger background packaging and export of deliverable audio files."""
    store = get_voice_project_store()
    preflight = VoiceProjectPreflight(store=store)
    try:
        preflight.validate_project_exists(project_id)
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)

    op_mgr = get_voice_project_operation_manager()
    service = get_voice_project_service(store=store)
    fmts = req.formats if req else ["wav"]

    try:
        op = op_mgr.submit(
            project_id,
            "export",
            service.export,
            project_id,
            formats=fmts,
        )
        return VoiceProjectOperationResponse(
            job_id=op.id,
            project_id=project_id,
            operation=op.operation,
            status=op.status.value,
            message="Audio export task scheduled successfully",
        )
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


@router.post(
    "/api/v1/voice-projects/{project_id}/finalize",
    response_model=VoiceProjectOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger Full Post-Production Finalization",
)
def trigger_finalize(project_id: str, req: FinalizeVoiceProjectRequest | None = None):
    """Trigger complete pipeline (prepare_mix -> mix -> master -> export) in a single background job."""
    store = get_voice_project_store()
    preflight = VoiceProjectPreflight(store=store)
    try:
        preflight.validate_project_exists(project_id)
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)

    op_mgr = get_voice_project_operation_manager()
    service = get_voice_project_service(store=store)
    m_prof = req.mastering_profile if req else "storytelling"
    fmts = req.output_formats if req else ["wav"]
    m_cfg = req.mix_config if req else None

    try:
        op = op_mgr.submit(
            project_id,
            "finalize",
            service.finalize,
            project_id,
            mix_config=m_cfg,
            mastering_profile=m_prof,
            output_formats=fmts,
        )
        return VoiceProjectOperationResponse(
            job_id=op.id,
            project_id=project_id,
            operation=op.operation,
            status=op.status.value,
            message="Finalization pipeline scheduled successfully",
        )
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


# =========================================================
# 4. Artifacts Discovery & Safe File Download
# =========================================================


@router.get(
    "/api/v1/voice-projects/{project_id}/artifacts",
    response_model=VoiceProjectArtifactsListResponse,
    summary="List Generated Artifacts",
)
def list_project_artifacts(project_id: str):
    """List all available deliverable audio and plan artifacts for a project."""
    service = get_voice_project_service()
    try:
        items = service.list_artifacts(project_id)
        return VoiceProjectArtifactsListResponse(
            project_id=project_id,
            artifacts=[ArtifactInfo(**item) for item in items],
        )
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


@router.get(
    "/api/v1/voice-projects/{project_id}/artifacts/{artifact_id}",
    summary="Download Specific Project Artifact",
)
def download_project_artifact(project_id: str, artifact_id: str):
    """Safely download an artifact audio or YAML file with path traversal protection."""
    store = get_voice_project_store()
    try:
        if not store.project_exists(project_id):
            raise VoiceProjectNotFound(f"Project '{project_id}' not found.")
        proj_dir = store.get_project_dir(project_id).resolve()

        # Map known artifact IDs to relative paths
        artifact_map = {
            "final_wav": proj_dir / "exports" / "FINAL.wav",
            "final_mp3": proj_dir / "exports" / "FINAL.mp3",
            "mix_plan": proj_dir / "mix-plan.yaml",
            "master_wav": proj_dir / "mix" / "master.wav",
            "premaster_wav": proj_dir / "mix" / "premaster.wav",
            "export_manifest": proj_dir / "exports" / "export-manifest.yaml",
        }

        target_file = artifact_map.get(artifact_id)
        if not target_file:
            # Check if artifact_id matches an attempt or custom file inside project_dir
            target_file = (proj_dir / artifact_id).resolve()

        target_file = target_file.resolve()

        # Security check: prevent directory traversal outside proj_dir
        if not str(target_file).startswith(str(proj_dir)) or not target_file.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Artifact '{artifact_id}' not found for project '{project_id}'.",
            )

        media_type = "audio/wav" if target_file.suffix == ".wav" else "application/octet-stream"
        if target_file.suffix in (".yaml", ".yml"):
            media_type = "application/x-yaml"

        return FileResponse(
            path=str(target_file),
            media_type=media_type,
            filename=target_file.name,
        )
    except HTTPException:
        raise
    except Exception as exc:
        return _handle_domain_error(exc, project_id=project_id)


# =========================================================
# 5. Operation Jobs Tracking & Cancellation
# =========================================================


@router.get(
    "/api/v1/voice-project-jobs/{job_id}",
    response_model=VoiceProjectJobResponse,
    summary="Get Operation Job Status",
)
def get_voice_project_job(job_id: str):
    """Retrieve execution status, current active beat, child TTS job ID, and progress percentage."""
    op_mgr = get_voice_project_operation_manager()
    op = op_mgr.get_operation(job_id)
    if not op:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Voice project operation job '{job_id}' not found.",
        )

    return VoiceProjectJobResponse(
        id=op.id,
        project_id=op.project_id,
        operation=op.operation,
        status=op.status.value if hasattr(op.status, "value") else str(op.status),
        stage=op.stage,
        beat_id=op.beat_id,
        child_job_id=op.child_job_id,
        progress_percent=op.progress_percent,
        message=op.message,
        created_at=op.created_at,
        updated_at=op.updated_at,
        result=op.result,
        error=op.error,
    )


@router.post(
    "/api/v1/voice-project-jobs/{job_id}/cancel",
    summary="Cancel Operation Job",
)
def cancel_voice_project_job(job_id: str):
    """Request cooperative cancellation of an active voice project operation."""
    op_mgr = get_voice_project_operation_manager()
    success, message = op_mgr.cancel_operation(job_id)
    if not success:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"success": False, "message": message},
        )
    return {"success": True, "message": message}
