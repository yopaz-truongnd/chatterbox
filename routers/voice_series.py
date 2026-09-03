"""FastAPI REST Router for Story Series & Batch Production (Phase 19).

Thin routing adapter mapping HTTP endpoints to VoiceSeriesService and
VoiceSeriesOperations.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from services.voice_project_models import InvalidProjectStateError, VoiceProjectNotFound
from services.voice_project_operations import OperationAlreadyRunningError
from services.voice_series_models import (
    SeriesHumanAction,
    SeriesProductionSummary,
    SeriesPronunciationBible,
    SeriesSoundBible,
    SeriesVoiceBible,
    VoiceSeries,
    VoiceSeriesEpisode,
)
from services.voice_series_operations import SeriesPreflightError, VoiceSeriesOperations
from services.voice_series_service import VoiceSeriesService

router = APIRouter(prefix="/api/v1/voice-series", tags=["voice-series"])

_series_service = VoiceSeriesService()
_series_ops = VoiceSeriesOperations(service=_series_service)


class CreateSeriesRequest(BaseModel):
    title: str
    description: str | None = None
    language: str = "en"
    voice_bible: SeriesVoiceBible | None = None
    pronunciation_bible: SeriesPronunciationBible | None = None
    sound_bible: SeriesSoundBible | None = None
    series_id: str | None = None


class AddEpisodeRequest(BaseModel):
    project_id: str
    title: str
    episode_number: int | None = None
    episode_id: str | None = None


class ProduceSeriesRequest(BaseModel):
    episode_ids: list[str] | None = None


@router.post("", response_model=VoiceSeries, status_code=201)
def create_series(body: CreateSeriesRequest) -> VoiceSeries:
    try:
        return _series_service.create_series(
            title=body.title,
            description=body.description,
            language=body.language,
            voice_bible=body.voice_bible,
            pronunciation_bible=body.pronunciation_bible,
            sound_bible=body.sound_bible,
            series_id=body.series_id,
        )
    except InvalidProjectStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("", response_model=list[VoiceSeries])
def list_series() -> list[VoiceSeries]:
    return _series_service.list_series()


@router.get("/{series_id}", response_model=VoiceSeries)
def get_series(series_id: str) -> VoiceSeries:
    try:
        return _series_service.get_series(series_id)
    except VoiceProjectNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/{series_id}", response_model=VoiceSeries)
def update_series(series_id: str, updates: dict[str, Any] = Body(...)) -> VoiceSeries:
    try:
        return _series_service.update_series(series_id, updates)
    except VoiceProjectNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{series_id}/episodes", response_model=VoiceSeriesEpisode, status_code=201)
def add_episode(series_id: str, body: AddEpisodeRequest) -> VoiceSeriesEpisode:
    try:
        return _series_service.add_episode(
            series_id=series_id,
            project_id=body.project_id,
            title=body.title,
            episode_number=body.episode_number,
            episode_id=body.episode_id,
        )
    except VoiceProjectNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except SeriesPreflightError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "issues": [issue.model_dump() for issue in exc.issues]},
        )
    except InvalidProjectStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/{series_id}/episodes", response_model=list[VoiceSeriesEpisode])
def list_episodes(series_id: str) -> list[VoiceSeriesEpisode]:
    try:
        return _series_service.list_episodes(series_id)
    except VoiceProjectNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{series_id}/produce", status_code=202)
def produce_series(series_id: str, body: ProduceSeriesRequest = Body(default_factory=ProduceSeriesRequest)) -> dict[str, Any]:
    try:
        op = _series_ops.submit_series(series_id=series_id, episode_ids=body.episode_ids)
        return op.to_dict()
    except VoiceProjectNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InvalidProjectStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except OperationAlreadyRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{series_id}/cancel")
def cancel_series(series_id: str) -> dict[str, Any]:
    try:
        series = _series_service.get_series(series_id)
        cancelled = _series_ops.cancel_series(series_id)
        return {
            "series_id": series_id,
            "status": "cancelling" if cancelled else "idle",
            "cancelled": cancelled,
            "message": "Series production cancellation initiated." if cancelled else "No active batch operation was running for series.",
        }
    except VoiceProjectNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{series_id}/review-queue", response_model=list[SeriesHumanAction])
def get_review_queue(series_id: str) -> list[SeriesHumanAction]:
    try:
        return _series_service.get_review_queue(series_id)
    except VoiceProjectNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{series_id}/artifacts")
def get_series_artifacts(series_id: str) -> dict[str, Any]:
    try:
        series = _series_service.get_series(series_id)
        episodes = _series_service.list_episodes(series_id)
        return {
            "series_id": series_id,
            "slug": series.slug,
            "episodes": [
                {
                    "episode_id": ep.episode_id,
                    "episode_number": ep.episode_number,
                    "title": ep.title,
                    "status": ep.status,
                    "artifacts": ep.final_artifacts,
                }
                for ep in episodes
            ],
        }
    except VoiceProjectNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
