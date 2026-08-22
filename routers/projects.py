"""FastAPI Router for Audio Projects Planning, Two-Gate Confirmation & Orchestration."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from services import project_planner
from services.exceptions import (
    ProjectNotApprovedError,
    ProjectNotFoundError,
    ProjectStateError,
    ValidationError,
)

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


class PrepareProjectRequest(BaseModel):
    topic: str = Field(min_length=1, description="Topic or concept of the audio production")
    initial_requirements: dict[str, Any] | None = Field(default=None, description="Pre-specified parameters")
    auto_defaults: bool = Field(default=False, description="Auto-fill defaults for missing fields")


class AnswerQuestionsRequest(BaseModel):
    answers: dict[str, Any] | str = Field(description="User answers to missing requirements")
    auto_defaults: bool = Field(default=False, description="Auto-fill remaining non-critical fields")


class ConfirmRequirementsRequest(BaseModel):
    confirmed: bool = Field(default=True, description="Confirm requirements (True) or cancel (False)")


class GenerateScriptRequest(BaseModel):
    custom_prompt: str | None = Field(default=None, description="Additional custom instructions for script generation")
    num_scenes: int | None = Field(default=None, description="Target number of scenes")


class ConfirmScriptRequest(BaseModel):
    confirmed: bool = Field(default=True, description="Approve script (True) or request revision (False)")
    script_text: str | None = Field(default=None, description="Optional updated script text edited by user")


class ConfirmProjectRequest(BaseModel):
    confirmed: bool = Field(default=True, description="Approve current gate (True) or reject (False)")


class RenderProjectRequest(BaseModel):
    script_text: str | None = Field(default=None, description="Narration script text override")
    character_id: str | None = Field(default=None, description="Target character ID override")
    quality_preset: str | None = Field(default=None, description="Quality preset (fast, balanced, expressive)")


@router.post("/prepare", status_code=status.HTTP_201_CREATED)
def prepare_project_endpoint(req: PrepareProjectRequest) -> dict:
    """Initialize a new audio project, extract parameters, and return missing questions."""
    try:
        return project_planner.prepare_project(
            topic=req.topic,
            initial_requirements=req.initial_requirements,
            auto_defaults=req.auto_defaults,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/{project_id}/answer")
def answer_project_questions_endpoint(project_id: str, req: AnswerQuestionsRequest) -> dict:
    """Submit answers to missing project requirements."""
    try:
        return project_planner.answer_project_questions(
            project_id=project_id,
            answers=req.answers,
            auto_defaults=req.auto_defaults,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ProjectStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/{project_id}/confirm-requirements")
def confirm_requirements_endpoint(project_id: str, req: ConfirmRequirementsRequest) -> dict:
    """Gate 1: Confirm project requirements and draft English outline & script."""
    try:
        return project_planner.confirm_requirements(
            project_id=project_id,
            confirmed=req.confirmed,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except (ProjectStateError, ValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/{project_id}/generate-script")
def generate_script_endpoint(project_id: str, req: GenerateScriptRequest) -> dict:
    """Generate or re-generate English outline and script for the project."""
    try:
        return project_planner.generate_script(
            project_id=project_id,
            custom_prompt=req.custom_prompt,
            num_scenes=req.num_scenes,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/{project_id}/confirm-script")
def confirm_script_endpoint(project_id: str, req: ConfirmScriptRequest) -> dict:
    """Gate 2: Confirm and approve the English script and scene outline."""
    try:
        return project_planner.confirm_script(
            project_id=project_id,
            confirmed=req.confirmed,
            script_text=req.script_text,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except (ProjectStateError, ValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/{project_id}/confirm")
def confirm_project_endpoint(project_id: str, req: ConfirmProjectRequest) -> dict:
    """Unified confirmation endpoint advancing through current gate."""
    try:
        return project_planner.confirm_project(
            project_id=project_id,
            confirmed=req.confirmed,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except (ProjectStateError, ValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/{project_id}/render")
def render_project_endpoint(project_id: str, req: RenderProjectRequest) -> dict:
    """Render speech synthesis for an approved project. Rejects unapproved projects with HTTP 400."""
    from api_app import job_manager
    try:
        return project_planner.render_project(
            project_id=project_id,
            script_text=req.script_text,
            character_id=req.character_id,
            quality_preset=req.quality_preset,
            job_manager=job_manager,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except (ProjectNotApprovedError, ProjectStateError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("/{project_id}")
def get_project_endpoint(project_id: str) -> dict:
    """Retrieve full project details and structured summary."""
    from api_app import job_manager
    try:
        return project_planner.get_project(project_id=project_id, job_manager=job_manager)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("")
def list_projects_endpoint() -> dict:
    """List all audio planning projects."""
    from api_app import job_manager
    projects = project_planner.list_projects(job_manager=job_manager)
    return {"projects": projects, "count": len(projects)}
