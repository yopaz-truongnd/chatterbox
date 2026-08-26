"""Voice Series Management Service (Phase 19).

Coordinates series creation, episode registration, series bible consistency,
and human review queues.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.voice_project_models import InvalidProjectStateError, VoiceProjectNotFound
from services.voice_series_models import (
    EpisodeStatus,
    SeriesHumanAction,
    SeriesPronunciationBible,
    SeriesSoundBible,
    SeriesStatus,
    SeriesVoiceBible,
    VoiceSeries,
    VoiceSeriesEpisode,
)
from services.voice_series_store import VoiceSeriesStore, get_voice_series_store


class VoiceSeriesService:
    """Business logic for story series lifecycle."""

    def __init__(self, store: VoiceSeriesStore | None = None) -> None:
        self.store = store or get_voice_series_store()

    def create_series(
        self,
        title: str,
        description: str | None = None,
        language: str = "en",
        voice_bible: SeriesVoiceBible | None = None,
        pronunciation_bible: SeriesPronunciationBible | None = None,
        sound_bible: SeriesSoundBible | None = None,
        series_id: str | None = None,
    ) -> VoiceSeries:
        sid = series_id or f"vser_{uuid.uuid4().hex[:10]}"
        if self.store.series_exists(sid):
            raise InvalidProjectStateError(f"Series '{sid}' already exists.")

        series = VoiceSeries(
            series_id=sid,
            title=title,
            description=description,
            language=language,
            voice_bible=voice_bible or SeriesVoiceBible(language=language),
            pronunciation_bible=pronunciation_bible or SeriesPronunciationBible(),
            sound_bible=sound_bible or SeriesSoundBible(),
            status=SeriesStatus.DRAFT,
        )
        self.store.save_series(series)
        return series

    def get_series(self, series_id: str) -> VoiceSeries:
        series = self.store.get_series(series_id)
        if not series:
            raise VoiceProjectNotFound(f"Series '{series_id}' not found.")
        return series

    def list_series(self) -> list[VoiceSeries]:
        return self.store.list_series()

    def update_series(self, series_id: str, updates: dict[str, Any]) -> VoiceSeries:
        """Update series metadata or bibles.

        INVARIANT: Updating series defaults does NOT mutate completed episodes.
        """
        series = self.get_series(series_id)
        data = series.model_dump()

        # Disallow changing series_id or created_at
        updates.pop("series_id", None)
        updates.pop("created_at", None)

        data.update(updates)
        data["updated_at"] = datetime.now(timezone.utc).isoformat()

        updated = VoiceSeries.model_validate(data)
        self.store.save_series(updated)
        return updated

    def add_episode(
        self,
        series_id: str,
        project_id: str,
        title: str,
        episode_number: int | None = None,
        episode_id: str | None = None,
    ) -> VoiceSeriesEpisode:
        """Register an existing or planned VoiceProject as an episode in the series."""
        series = self.get_series(series_id)

        episodes = self.store.list_episodes(series_id)
        num = episode_number or (len(episodes) + 1)
        eid = episode_id or f"ep_{uuid.uuid4().hex[:8]}"

        # Validate unique episode number
        if any(e.episode_number == num for e in episodes):
            raise InvalidProjectStateError(
                f"Episode number {num} already exists in series '{series_id}'."
            )

        episode = VoiceSeriesEpisode(
            episode_id=eid,
            series_id=series_id,
            project_id=project_id,
            episode_number=num,
            title=title,
            status=EpisodeStatus.PENDING,
        )
        self.store.save_episode(episode)

        # Update episode order in series
        if eid not in series.episode_order:
            series.episode_order.append(eid)
            series.updated_at = datetime.now(timezone.utc).isoformat()
            self.store.save_series(series)

        return episode

    def get_episode(self, series_id: str, episode_id: str) -> VoiceSeriesEpisode:
        ep = self.store.get_episode(series_id, episode_id)
        if not ep:
            raise VoiceProjectNotFound(f"Episode '{episode_id}' not found in series '{series_id}'.")
        return ep

    def list_episodes(self, series_id: str) -> list[VoiceSeriesEpisode]:
        self.get_series(series_id)
        return self.store.list_episodes(series_id)

    def get_review_queue(self, series_id: str) -> list[SeriesHumanAction]:
        """Aggregate pending human action gates across all episodes in the series."""
        self.get_series(series_id)
        episodes = self.store.list_episodes(series_id)
        actions: list[SeriesHumanAction] = []

        from services.voice_project_dependencies import (
            get_voice_project_store,
            get_voice_project_workflow_service,
        )

        wf_service = get_voice_project_workflow_service()
        proj_store = get_voice_project_store()

        for ep in episodes:
            if ep.workflow_id:
                try:
                    wf = wf_service.store.get_workflow(ep.workflow_id)
                    if wf and wf.human_action:
                        # Extract master_wav sha256 if available
                        master_path = proj_store.get_project_dir(ep.project_id) / "mix" / "master.wav"
                        sha = None
                        if master_path.exists():
                            from services.voice_project_service import compute_file_sha256
                            sha = compute_file_sha256(master_path)

                        actions.append(
                            SeriesHumanAction(
                                episode_id=ep.episode_id,
                                project_id=ep.project_id,
                                action_type=wf.human_action.get("type", "approval_required"),
                                reason=wf.human_action.get("reason", "Final review required"),
                                items=wf.human_action.get("items", []),
                                available_options=wf.human_action.get("options", ["approve", "reject"]),
                                artifact_id="master_wav",
                                artifact_sha256=sha,
                            )
                        )
                except Exception:
                    pass

        return actions
