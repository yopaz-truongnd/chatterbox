"""FastAPI REST Router for Voice Workflows (Phase 15).

Provides autonomous multi-step orchestration endpoints for end-to-end audio production.
"""

from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from schemas.voice_workflows import (
    ApproveVoiceWorkflowRequest,
    CreateVoiceWorkflowRequest,
    VoiceWorkflowResponse,
    WorkflowPolicySchema,
    WorkflowStepSchema,
)
from services.voice_project_workflow import VoiceProjectWorkflowService
from services.voice_project_workflow_models import VoiceWorkflowState, WorkflowPolicy
from services.voice_project_models import InvalidProjectStateError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice-workflows"])


def _format_workflow_response(state: VoiceWorkflowState) -> VoiceWorkflowResponse:
    """Map internal VoiceWorkflowState to public REST schema."""
    return VoiceWorkflowResponse(
        workflow_id=state.workflow_id,
        project_id=state.project_id,
        status=state.status.value if hasattr(state.status, "value") else str(state.status),
        policy=WorkflowPolicySchema.model_validate(state.policy.model_dump()),
        steps=[
            WorkflowStepSchema(
                name=s.name,
                status=s.status,
                operation_id=s.operation_id,
                progress_percent=s.progress_percent,
                started_at=s.started_at,
                completed_at=s.completed_at,
                result_summary=s.result_summary,
                error=s.error,
            )
            for s in state.steps
        ],
        current_step=state.current_step,
        human_action=state.human_action,
        suggested_action=state.suggested_action,
        created_at=state.created_at,
        updated_at=state.updated_at,
        result=state.result,
        error=state.error,
    )


@router.post(
    "/api/v1/voice-workflows",
    response_model=VoiceWorkflowResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Launch Autonomous Voice Workflow",
)
def create_voice_workflow(req: CreateVoiceWorkflowRequest):
    """Launch autonomous end-to-end production workflow."""
    service = VoiceProjectWorkflowService()
    policy = WorkflowPolicy.model_validate(req.policy.model_dump())
    state = service.start_workflow(
        script_text=req.script_text,
        project_id=req.project_id,
        title=req.title,
        language=req.language,
        policy=policy,
    )
    return _format_workflow_response(state)


@router.get(
    "/api/v1/voice-workflows/{workflow_id}",
    response_model=VoiceWorkflowResponse,
    summary="Get Voice Workflow Status",
)
def get_voice_workflow(workflow_id: str):
    """Retrieve execution status, current step, and human action gates."""
    service = VoiceProjectWorkflowService()
    state = service.get_workflow(workflow_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Voice workflow '{workflow_id}' not found.",
        )
    return _format_workflow_response(state)


@router.post(
    "/api/v1/voice-workflows/{workflow_id}/resume",
    response_model=VoiceWorkflowResponse,
    summary="Resume Paused Voice Workflow",
)
def resume_voice_workflow(workflow_id: str):
    """Resume execution of a workflow paused at a human action gate."""
    service = VoiceProjectWorkflowService()
    try:
        state = service.resume_workflow(workflow_id)
        return _format_workflow_response(state)
    except InvalidProjectStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot resume workflow: {str(exc)}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot resume workflow: {str(exc)}",
        )


@router.post(
    "/api/v1/voice-workflows/{workflow_id}/approve",
    response_model=VoiceWorkflowResponse,
    summary="Approve Workflow Human Gate",
)
def approve_voice_workflow(workflow_id: str, req: ApproveVoiceWorkflowRequest):
    """Record an explicit human decision and continue the workflow."""
    service = VoiceProjectWorkflowService()
    try:
        state = service.approve_workflow(
            workflow_id,
            action=req.action,
            approved=req.approved,
            artifact_id=req.artifact_id,
            artifact_sha256=req.artifact_sha256,
        )
        return _format_workflow_response(state)
    except InvalidProjectStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post(
    "/api/v1/voice-workflows/{workflow_id}/cancel",
    summary="Cancel Voice Workflow",
)
def cancel_voice_workflow(workflow_id: str):
    """Cancel in-flight workflow and active background operations."""
    service = VoiceProjectWorkflowService()
    success, message = service.cancel_workflow(workflow_id)
    if not success:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"success": False, "message": message},
        )
    return {"success": True, "message": message}
