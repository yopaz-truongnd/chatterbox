"""Batch Series Production Operations (Phase 19).

Coordinates concurrent execution of multi-episode series workflows with:
- Concurrency limiting (max_parallel_episodes)
- Bible inheritance (voice/pronunciation/sound bibles)
- Deliverable export packaging (exports/series-{slug}/episode-001/)
- Resilient error handling (one episode failure does not corrupt others)
- Cooperative cancellation & restart recovery
"""

from __future__ import annotations

import concurrent.futures
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
import uuid
import yaml

from services.voice_project_models import InvalidProjectStateError
from services.voice_project_operations import CancellationToken
from services.voice_project_workflow_models import WorkflowPolicy
from services.voice_series_models import (
    EpisodeStatus,
    SeriesHumanAction,
    SeriesProductionSummary,
    SeriesStatus,
    VoiceSeries,
    VoiceSeriesEpisode,
    make_safe_slug,
)
from services.voice_series_service import VoiceSeriesService
from services.voice_series_store import VoiceSeriesStore, get_voice_series_store


class VoiceSeriesOperations:
    """Coordinator for batch production of series episodes."""

    def __init__(
        self,
        service: VoiceSeriesService | None = None,
        store: VoiceSeriesStore | None = None,
        proj_store: Any | None = None,
        proj_service: Any | None = None,
        wf_service: Any | None = None,
    ) -> None:
        self.store = store or get_voice_series_store()
        self.service = service or VoiceSeriesService(store=self.store)
        self._proj_store = proj_store
        self._proj_service = proj_service
        self._wf_service = wf_service

    def _package_episode_deliverables(
        self,
        series: VoiceSeries,
        episode: VoiceSeriesEpisode,
        export_root: Path,
    ) -> dict[str, str]:
        """Copy completed episode deliverables to exports/series-{slug}/episode-NNN/."""
        from services.voice_project_dependencies import get_voice_project_store
        proj_store = self._proj_store or get_voice_project_store()
        proj_dir = proj_store.get_project_dir(episode.project_id)
        exp_src_dir = proj_dir / "exports"
        if not exp_src_dir.exists():
            exp_src_dir = proj_dir / "output"

        slug = series.slug
        ep_folder = f"episode-{episode.episode_number:03d}"
        dest_dir = export_root / slug / ep_folder
        dest_dir.mkdir(parents=True, exist_ok=True)

        copied = {}
        for fname in ["FINAL.wav", "FINAL.mp3", "export-manifest.yaml"]:
            src = exp_src_dir / fname
            if src.exists():
                dst = dest_dir / fname
                shutil.copy2(src, dst)
                copied[fname] = str(dst)

        # Write series-level manifests
        series_dir = export_root / slug
        manifest_path = series_dir / "series-manifest.yaml"
        with open(manifest_path, "w", encoding="utf-8") as fh:
            fh.write(yaml.safe_dump({
                "series_id": series.series_id,
                "title": series.title,
                "language": series.language,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }))

        voice_bible_path = series_dir / "voice-bible.yaml"
        with open(voice_bible_path, "w", encoding="utf-8") as fh:
            fh.write(yaml.safe_dump(series.voice_bible.model_dump()))

        pron_bible_path = series_dir / "pronunciation-bible.yaml"
        with open(pron_bible_path, "w", encoding="utf-8") as fh:
            fh.write(yaml.safe_dump(series.pronunciation_bible.model_dump()))

        return copied

    def produce_series(
        self,
        series_id: str,
        episode_ids: list[str] | None = None,
        cancellation_token: CancellationToken | None = None,
        progress_callback: Callable[[str, float, dict[str, Any]], None] | None = None,
        export_root: Path | str | None = None,
    ) -> SeriesProductionSummary:
        """Execute production workflow for requested episodes in the series."""
        series = self.service.get_series(series_id)
        all_episodes = self.store.list_episodes(series_id)

        target_episodes = [
            e for e in all_episodes
            if episode_ids is None or e.episode_id in episode_ids
        ]

        if not target_episodes:
            raise InvalidProjectStateError(f"No matching episodes to produce for series '{series_id}'.")

        op_id = f"sop_{uuid.uuid4().hex[:10]}"
        max_workers = min(series.production_policy.max_parallel_episodes, len(target_episodes))
        exp_root = Path(export_root or "exports")

        from services.voice_project_dependencies import (
            get_voice_project_service,
            get_voice_project_store,
            get_voice_project_workflow_service,
        )

        wf_service = self._wf_service or get_voice_project_workflow_service()
        proj_service = self._proj_service or get_voice_project_service(provider_name=series.voice_bible.provider)
        proj_store = self._proj_store or get_voice_project_store()

        # Build policy from series bibles
        policy = WorkflowPolicy(
            provider=series.voice_bible.provider,
            mixing_profile=series.sound_bible.mastering_profile,
            mastering_profile=series.sound_bible.mastering_profile,
            output_formats=series.sound_bible.output_formats,
            require_final_approval=series.production_policy.require_human_approval,
        )

        def produce_single_episode(ep: VoiceSeriesEpisode) -> dict[str, Any]:
            if cancellation_token and cancellation_token.is_cancelled():
                ep.status = EpisodeStatus.CANCELLED
                self.store.save_episode(ep)
                return {"episode_id": ep.episode_id, "status": "cancelled"}

            # Check if already completed
            if ep.status == EpisodeStatus.COMPLETED:
                return {"episode_id": ep.episode_id, "status": "completed", "skipped": True}

            ep.status = EpisodeStatus.PRODUCING
            self.store.save_episode(ep)

            try:
                # Load project source script
                state = proj_store.get_project_state(ep.project_id)
                script_path = proj_store.get_project_dir(ep.project_id) / "source-script.txt"
                script_text = script_path.read_text(encoding="utf-8") if script_path.exists() else ""

                # Apply pronunciation overrides if any
                if series.pronunciation_bible.overrides:
                    from services.director_resource_service import DirectorResourceService
                    dres = DirectorResourceService(proj_service)
                    for term, pron in series.pronunciation_bible.overrides.items():
                        try:
                            dres.override_pronunciation(ep.project_id, term, pron, actor_id="series_bible")
                        except Exception:
                            pass

                # Run or resume workflow
                wf = wf_service.start_workflow(
                    script_text=script_text,
                    project_id=ep.project_id,
                    title=ep.title,
                    language=series.language,
                    policy=policy,
                )
                ep.workflow_id = wf.workflow_id
                self.store.save_episode(ep)

                # Wait for workflow completion or human action
                while True:
                    if cancellation_token and cancellation_token.is_cancelled():
                        wf_service.cancel_workflow(wf.workflow_id)
                        ep.status = EpisodeStatus.CANCELLED
                        self.store.save_episode(ep)
                        return {"episode_id": ep.episode_id, "status": "cancelled"}

                    st = wf_service.get_workflow(wf.workflow_id)
                    if not st:
                        break

                    if st.status == "waiting_for_human" or getattr(st.status, "value", str(st.status)) == "waiting_for_human":
                        ep.status = EpisodeStatus.WAITING_FOR_HUMAN
                        ep.review_required = True
                        self.store.save_episode(ep)
                        return {"episode_id": ep.episode_id, "status": "waiting_for_human"}

                    if st.status == "completed" or getattr(st.status, "value", str(st.status)) == "completed":
                        ep.status = EpisodeStatus.COMPLETED
                        ep.published_at = datetime.now(timezone.utc).isoformat()
                        # Package deliverables
                        copied = self._package_episode_deliverables(series, ep, exp_root)
                        ep.final_artifacts = copied
                        self.store.save_episode(ep)
                        return {"episode_id": ep.episode_id, "status": "completed"}

                    if st.status in ("failed", "cancelled", "interrupted") or getattr(st.status, "value", str(st.status)) in ("failed", "cancelled", "interrupted"):
                        ep.status = EpisodeStatus.CANCELLED if getattr(st.status, "value", str(st.status)) == "cancelled" else EpisodeStatus.FAILED
                        ep.error = st.error
                        self.store.save_episode(ep)
                        return {"episode_id": ep.episode_id, "status": ep.status.value, "error": st.error}

                    import time
                    time.sleep(0.05)

                ep.status = EpisodeStatus.FAILED
                self.store.save_episode(ep)
                return {"episode_id": ep.episode_id, "status": "failed", "error": "Workflow ended unexpectedly"}

            except Exception as exc:
                ep.status = EpisodeStatus.FAILED
                ep.error = {"message": str(exc)}
                self.store.save_episode(ep)
                return {"episode_id": ep.episode_id, "status": "failed", "error": str(exc)}

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_ep = {executor.submit(produce_single_episode, ep): ep for ep in target_episodes}
            for future in concurrent.futures.as_completed(future_to_ep):
                try:
                    res = future.result()
                    results.append(res)
                except Exception as exc:
                    ep = future_to_ep[future]
                    results.append({"episode_id": ep.episode_id, "status": "failed", "error": str(exc)})

        # Aggregate counts
        ep_states = self.store.list_episodes(series_id)
        completed_count = sum(1 for e in ep_states if e.status == EpisodeStatus.COMPLETED)
        failed_count = sum(1 for e in ep_states if e.status == EpisodeStatus.FAILED)
        waiting_count = sum(1 for e in ep_states if e.status == EpisodeStatus.WAITING_FOR_HUMAN)
        cancelled_count = sum(1 for e in ep_states if e.status == EpisodeStatus.CANCELLED)
        running_count = sum(1 for e in ep_states if e.status == EpisodeStatus.PRODUCING)
        queued_count = sum(1 for e in ep_states if e.status in (EpisodeStatus.PENDING, EpisodeStatus.QUEUED))

        total = len(ep_states)
        progress = (completed_count / total * 100.0) if total > 0 else 0.0

        human_actions = self.service.get_review_queue(series_id)

        # Update series status
        if completed_count == total and total > 0:
            series.status = SeriesStatus.COMPLETED
        else:
            series.status = SeriesStatus.ACTIVE
        series.updated_at = datetime.now(timezone.utc).isoformat()
        self.store.save_series(series)

        return SeriesProductionSummary(
            series_id=series_id,
            operation_id=op_id,
            total_episodes=total,
            queued=queued_count,
            running=running_count,
            completed=completed_count,
            waiting_for_human=waiting_count,
            failed=failed_count,
            cancelled=cancelled_count,
            progress_percent=progress,
            episode_results=results,
            human_actions=human_actions,
            suggested_action="Review completed episodes or address pending human review gates.",
        )
