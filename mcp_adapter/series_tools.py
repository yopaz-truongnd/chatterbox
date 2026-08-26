"""MCP Series Tools Adapter (Phase 19).

Thin protocol adapter for AI agents to interact with VoiceSeriesService and
VoiceSeriesOperations.
"""

from __future__ import annotations

import json
from typing import Any, Callable


def _success(data: Any) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(data, indent=2, ensure_ascii=False)}],
        "isError": False,
    }


def _error(msg: str, code: str = "ERROR", details: dict[str, Any] | None = None) -> dict:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps({"error": {"code": code, "message": msg, **(details or {})}}, indent=2),
            }
        ],
        "isError": True,
    }


def handle_series_create(args: dict[str, Any], request_fn: Callable | None = None) -> dict[str, Any]:
    title = args.get("title")
    if not title:
        return _error("title is required", code="INVALID_ARGUMENTS")

    try:
        from services.voice_series_service import VoiceSeriesService
        from services.voice_series_models import SeriesVoiceBible, SeriesPronunciationBible, SeriesSoundBible

        service = VoiceSeriesService()
        vb = SeriesVoiceBible(**args["voice_bible"]) if "voice_bible" in args else None
        pb = SeriesPronunciationBible(**args["pronunciation_bible"]) if "pronunciation_bible" in args else None
        sb = SeriesSoundBible(**args["sound_bible"]) if "sound_bible" in args else None

        res = service.create_series(
            title=title,
            description=args.get("description"),
            language=args.get("language", "en"),
            voice_bible=vb,
            pronunciation_bible=pb,
            sound_bible=sb,
            series_id=args.get("series_id"),
        )
        return _success(res.model_dump(mode="json"))
    except Exception as exc:
        return _error(f"Failed to create series: {exc}", code="SERIES_CREATE_FAILED")


def handle_series_get(args: dict[str, Any], request_fn: Callable | None = None) -> dict[str, Any]:
    series_id = args.get("series_id")
    if not series_id:
        return _error("series_id is required", code="INVALID_ARGUMENTS")
    try:
        from services.voice_series_service import VoiceSeriesService
        service = VoiceSeriesService()
        series = service.get_series(series_id)
        episodes = service.list_episodes(series_id)
        data = series.model_dump(mode="json")
        data["episodes"] = [e.model_dump(mode="json") for e in episodes]
        return _success(data)
    except Exception as exc:
        return _error(f"Failed to get series: {exc}", code="SERIES_GET_FAILED")


def handle_series_add_episode(args: dict[str, Any], request_fn: Callable | None = None) -> dict[str, Any]:
    series_id = args.get("series_id")
    project_id = args.get("project_id")
    title = args.get("title")
    if not series_id or not project_id or not title:
        return _error("series_id, project_id, and title are required", code="INVALID_ARGUMENTS")
    try:
        from services.voice_series_service import VoiceSeriesService
        service = VoiceSeriesService()
        ep = service.add_episode(
            series_id=series_id,
            project_id=project_id,
            title=title,
            episode_number=args.get("episode_number"),
            episode_id=args.get("episode_id"),
        )
        return _success(ep.model_dump(mode="json"))
    except Exception as exc:
        return _error(f"Failed to add episode: {exc}", code="EPISODE_ADD_FAILED")


def handle_series_produce(args: dict[str, Any], request_fn: Callable | None = None) -> dict[str, Any]:
    series_id = args.get("series_id")
    if not series_id:
        return _error("series_id is required", code="INVALID_ARGUMENTS")
    try:
        from services.voice_series_operations import SeriesPreflightError, VoiceSeriesOperations
        ops = VoiceSeriesOperations()
        try:
            operation = ops.submit_series(
                series_id=series_id,
                episode_ids=args.get("episode_ids"),
            )
        except SeriesPreflightError as exc:
            return _error(
                "Series production preflight failed.", code="VALIDATION_ERROR",
                details={"issues": [issue.model_dump() for issue in exc.issues]},
            )
        return _success(operation.to_dict())
    except Exception as exc:
        return _error(f"Failed to produce series: {exc}", code="SERIES_PRODUCE_FAILED")


def handle_series_status(args: dict[str, Any], request_fn: Callable | None = None) -> dict[str, Any]:
    return handle_series_get(args, request_fn=request_fn)


def handle_series_review_queue(args: dict[str, Any], request_fn: Callable | None = None) -> dict[str, Any]:
    series_id = args.get("series_id")
    if not series_id:
        return _error("series_id is required", code="INVALID_ARGUMENTS")
    try:
        from services.voice_series_service import VoiceSeriesService
        service = VoiceSeriesService()
        actions = service.get_review_queue(series_id)
        return _success([a.model_dump(mode="json") for a in actions])
    except Exception as exc:
        return _error(f"Failed to get review queue: {exc}", code="REVIEW_QUEUE_FAILED")


def handle_series_cancel(args: dict[str, Any], request_fn: Callable | None = None) -> dict[str, Any]:
    series_id = args.get("series_id")
    if not series_id:
        return _error("series_id is required", code="INVALID_ARGUMENTS")
    try:
        from services.voice_series_operations import VoiceSeriesOperations
        cancelled = VoiceSeriesOperations().cancel_series(series_id)
        return _success({
            "series_id": series_id,
            "status": "cancelling" if cancelled else "idle",
            "cancelled": cancelled,
        })
    except Exception as exc:
        return _error(f"Failed to cancel series: {exc}", code="SERIES_CANCEL_FAILED")
