"""FastAPI Router for Audio Projects Planning, Requirements Gathering & Lifecycle Confirmation."""

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
    topic: str = Field(min_length=1, description="Chủ đề của sản phẩm âm thanh")
    initial_requirements: dict[str, Any] | None = Field(default=None, description="Các tham số yêu cầu ban đầu (nếu có)")
    auto_defaults: bool = Field(default=False, description="Tự động điền giá trị mặc định cho các trường recommended")


class AnswerQuestionsRequest(BaseModel):
    answers: dict[str, Any] | str = Field(description="Câu trả lời cho các câu hỏi còn thiếu (dict hoặc văn bản tự nhiên)")
    auto_defaults: bool = Field(default=False, description="Tự động điền giá trị mặc định cho các mục còn lại")


class ConfirmProjectRequest(BaseModel):
    confirmed: bool = Field(default=True, description="Xác nhận phê duyệt (True) hoặc từ chối/hủy (False)")


class RenderProjectRequest(BaseModel):
    script_text: str | None = Field(default=None, description="Văn bản kịch bản tùy chỉnh để render. Để trống để dùng kịch bản sinh tự động.")
    character_id: str | None = Field(default=None, description="Mã nhân vật/giọng đọc chỉ định ghi đè.")
    quality_preset: str | None = Field(default=None, description="Chất lượng preset ghi đè (fast, balanced, expressive).")


@router.post("/prepare", status_code=status.HTTP_201_CREATED)
def prepare_project_endpoint(req: PrepareProjectRequest) -> dict:
    """Initialize a new audio project, extract available parameters, and return single-batch missing questions."""
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
    """Submit answers to missing project questions, update requirements, and advance lifecycle."""
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


@router.post("/{project_id}/confirm")
def confirm_project_endpoint(project_id: str, req: ConfirmProjectRequest) -> dict:
    """Explicitly confirm and approve the final project configuration before synthesis."""
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
    """Render and synthesize speech for an approved project. Rejects unapproved projects with HTTP 400."""
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
    except ProjectNotApprovedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("/{project_id}")
def get_project_endpoint(project_id: str) -> dict:
    """Retrieve full project details and structured summary."""
    try:
        return project_planner.get_project(project_id=project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("")
def list_projects_endpoint() -> dict:
    """List all audio planning projects."""
    projects = project_planner.list_projects()
    return {"projects": projects, "count": len(projects)}
