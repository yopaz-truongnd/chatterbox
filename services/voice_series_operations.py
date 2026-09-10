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

from services.voice_project_models import InvalidProjectStateError, compute_file_sha256
from services.voice_project_operations import (
    CancellationToken,
    OperationAlreadyRunningError,
    OperationStatus,
    VoiceProjectOperationManager,
)
from services.voice_project_workflow_models import WorkflowPolicy
from services.voice_series_models import (
    EpisodeStatus,
    SeriesHumanAction,
    SeriesPronunciationBible,
    SeriesProductionPolicy,
    SeriesProductionSummary,
    SeriesSoundBible,
    SeriesStatus,
    SeriesVoiceBible,
    VoiceSeries,
    VoiceSeriesEpisode,
    make_safe_slug,
)
from services.voice_series_service import VoiceSeriesService
from services.voice_series_store import VoiceSeriesStore, get_voice_series_store
import threading

_active_series_tokens: dict[str, CancellationToken] = {}
_tokens_lock = threading.Lock()


class SeriesPreflightError(InvalidProjectStateError):
    def __init__(self, issues: list[Any]) -> None:
        self.issues = issues
        super().__init__("Series production preflight failed.")


class SeriesPublishCancelled(Exception):
    pass


class VoiceSeriesOperations:
    """Coordinator for batch production of series episodes."""

    def __init__(
        self,
        service: VoiceSeriesService | None = None,
        store: VoiceSeriesStore | None = None,
        proj_store: Any | None = None,
        proj_service: Any | None = None,
        wf_service: Any | None = None,
        event_store: Any | None = None,
        operation_manager: VoiceProjectOperationManager | None = None,
    ) -> None:
        self.store = store or get_voice_series_store()
        self.service = service or VoiceSeriesService(store=self.store)
        self._proj_store = proj_store
        self._proj_service = proj_service
        self._wf_service = wf_service
        self._event_store = event_store
        self._operation_manager = operation_manager

    @staticmethod
    def _operation_scope(series_id: str) -> str:
        return f"series_{series_id}"

    def _operations(self) -> VoiceProjectOperationManager:
        if self._operation_manager is None:
            from services.voice_project_dependencies import get_voice_project_operation_manager
            self._operation_manager = get_voice_project_operation_manager()
        return self._operation_manager

    @staticmethod
    def _episode_settings(series: VoiceSeries, episode: VoiceSeriesEpisode):
        snapshot = episode.production_snapshot or {}
        return (
            SeriesVoiceBible.model_validate(snapshot.get("voice_bible", series.voice_bible)),
            SeriesPronunciationBible.model_validate(
                snapshot.get("pronunciation_bible", series.pronunciation_bible)
            ),
            SeriesSoundBible.model_validate(snapshot.get("sound_bible", series.sound_bible)),
            SeriesProductionPolicy.model_validate(
                snapshot.get("production_policy", series.production_policy)
            ),
        )

    def submit_series(self, series_id: str, episode_ids: list[str] | None = None):
        series = self.service.get_series(series_id)
        episodes = [
            episode for episode in self.store.list_episodes(series_id)
            if episode_ids is None or episode.episode_id in episode_ids
        ]
        if not episodes:
            raise InvalidProjectStateError(f"No matching episodes to produce for series '{series_id}'.")
        from services.local_runtime_service import LocalRuntimeService
        runtime = LocalRuntimeService()
        errors = []
        for episode in episodes:
            if episode.status == EpisodeStatus.COMPLETED:
                continue
            voice_bible, _, sound_bible, _ = self._episode_settings(series, episode)
            errors.extend(issue for issue in runtime.run_production_preflight(
                episode.project_id,
                provider=voice_bible.provider,
                requested_formats=sound_bible.output_formats,
                selected_model=voice_bible.model,
                reference_voice=voice_bible.narrator_reference_voice,
            ) if issue.severity == "error")
        if errors:
            raise SeriesPreflightError(errors)
        return self._operations().submit(
            self._operation_scope(series_id), "produce_series",
            self.produce_series, series_id, episode_ids,
        )

    def cancel_series(self, series_id: str) -> bool:
        """Cooperatively cancel any running batch production for the series."""
        active = self._operations().list_operations(project_id=self._operation_scope(series_id), limit=1)
        if active and active[0].status in (OperationStatus.QUEUED, OperationStatus.RUNNING, OperationStatus.CANCELLING):
            return self._operations().cancel_operation(active[0].id)[0]
        with _tokens_lock:
            token = _active_series_tokens.get(series_id)
            if token is not None:
                token.cancel()
                return True
        return False

    def _package_episode_deliverables(
        self,
        series: VoiceSeries,
        episode: VoiceSeriesEpisode,
        export_root: Path,
        cancellation_token: CancellationToken,
    ) -> dict[str, str]:
        """Verify and atomically publish one episode deliverable directory."""
        from services.voice_project_dependencies import get_voice_project_store
        proj_store = self._proj_store or get_voice_project_store()
        proj_dir = proj_store.get_project_dir(episode.project_id)
        exp_src_dir = proj_dir / "exports"
        if not exp_src_dir.exists():
            exp_src_dir = proj_dir / "output"

        slug = series.slug
        ep_folder = f"episode-{episode.episode_number:03d}"
        dest_dir = export_root / slug / ep_folder
        series_dir = export_root / slug
        series_dir.mkdir(parents=True, exist_ok=True)
        staging_dir = series_dir / f".{ep_folder}.{uuid.uuid4().hex}.tmp"

        manifest_src = exp_src_dir / "export-manifest.yaml"
        manifest = yaml.safe_load(manifest_src.read_text(encoding="utf-8")) or {}
        if manifest.get("project_id") != episode.project_id:
            raise ValueError("Export manifest project lineage does not match episode project.")
        expected = {
            Path(item["file_path"]).name: item["sha256"]
            for item in manifest.get("artifacts", [])
            if item.get("file_path") and item.get("sha256")
        }
        if not expected:
            raise ValueError("Export manifest contains no checksummed artifacts.")

        copied: dict[str, str] = {}
        try:
            staging_dir.mkdir()
            for fname, expected_sha in expected.items():
                if cancellation_token.is_cancelled():
                    raise SeriesPublishCancelled()
                src = exp_src_dir / fname
                if not src.is_file():
                    raise FileNotFoundError(f"Manifest artifact is missing: {fname}")
                dst = staging_dir / fname
                shutil.copy2(src, dst)
                actual_sha = compute_file_sha256(dst)
                if actual_sha != expected_sha:
                    raise ValueError(f"Checksum mismatch while packaging {fname}.")

            shutil.copy2(manifest_src, staging_dir / manifest_src.name)
            if cancellation_token.is_cancelled():
                raise SeriesPublishCancelled()
            os.replace(staging_dir, dest_dir)
            copied = {fname: str(dest_dir / fname) for fname in expected}
            copied[manifest_src.name] = str(dest_dir / manifest_src.name)
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)

        return copied

    @staticmethod
    def _write_series_manifests(series: VoiceSeries, export_root: Path) -> None:
        """Atomically write shared series metadata once per completed batch."""
        series_dir = export_root / series.slug
        series_dir.mkdir(parents=True, exist_ok=True)
        documents = {
            "series-manifest.yaml": {
                "series_id": series.series_id,
                "title": series.title,
                "language": series.language,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            "voice-bible.yaml": series.voice_bible.model_dump(),
            "pronunciation-bible.yaml": series.pronunciation_bible.model_dump(),
        }
        for filename, document in documents.items():
            target = series_dir / filename
            temporary = series_dir / f".{filename}.{uuid.uuid4().hex}.tmp"
            try:
                temporary.write_text(yaml.safe_dump(document), encoding="utf-8")
                os.replace(temporary, target)
            finally:
                if temporary.exists():
                    temporary.unlink()

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

        token = cancellation_token or CancellationToken()
        with _tokens_lock:
            if series_id in _active_series_tokens:
                raise OperationAlreadyRunningError(series_id, "direct", "produce_series")
            _active_series_tokens[series_id] = token

        op_id = f"sop_{uuid.uuid4().hex[:10]}"
        max_workers = min(series.production_policy.max_parallel_episodes, len(target_episodes))
        exp_root = Path(export_root or "exports")

        from services.voice_project_dependencies import (
            get_voice_project_service,
            get_voice_project_store,
            get_voice_project_workflow_service,
        )
        from services.production_event_models import ProductionEvent, ProductionEventType
        from services.production_event_store import get_production_event_store
        from services.local_runtime_service import LocalRuntimeService

        evt_store = self._event_store or get_production_event_store()
        runtime_svc = LocalRuntimeService()

        wf_service = self._wf_service or get_voice_project_workflow_service()
        proj_service = self._proj_service or get_voice_project_service(provider_name=series.voice_bible.provider)
        proj_store = self._proj_store or get_voice_project_store()

        evt_store.append_series_event(ProductionEvent(
            series_id=series_id,
            event_type=ProductionEventType.WORKFLOW_STARTED,
            message=f"Batch production initiated for series '{series.title}' ({len(target_episodes)} episodes).",
        ))

        def produce_single_episode(ep: VoiceSeriesEpisode) -> dict[str, Any]:
            if token.is_cancelled():
                ep.status = EpisodeStatus.CANCELLED
                self.store.save_episode(ep)
                evt_store.append_project_event(ProductionEvent(
                    project_id=ep.project_id,
                    series_id=series_id,
                    episode_id=ep.episode_id,
                    event_type=ProductionEventType.WORKFLOW_CANCELLED,
                    message=f"Episode '{ep.title}' production cancelled.",
                ))
                return {"episode_id": ep.episode_id, "status": "cancelled"}

            # Check if already completed
            if ep.status == EpisodeStatus.COMPLETED:
                return {"episode_id": ep.episode_id, "status": "completed", "skipped": True}

            voice_bible, pronunciation_bible, sound_bible, production_policy = self._episode_settings(series, ep)
            policy = WorkflowPolicy(
                provider=voice_bible.provider,
                mixing_profile=sound_bible.mixing_profile,
                mastering_profile=sound_bible.mastering_profile,
                output_formats=sound_bible.output_formats,
                require_final_approval=production_policy.require_human_approval,
                model=voice_bible.model,
                narrator_character=voice_bible.narrator_character,
                narrator_reference_voice=voice_bible.narrator_reference_voice,
                voice_style=voice_bible.voice_style,
                ambience_palette=sound_bible.ambience_palette,
                sfx_palette=sound_bible.sfx_palette,
                loudness_target_lufs=sound_bible.loudness_target_lufs,
                pronunciation_overrides=pronunciation_bible.overrides,
            )

            # 1. Mandatory Preflight Gate before scheduling
            preflight_issues = runtime_svc.run_production_preflight(
                ep.project_id,
                provider=voice_bible.provider,
                requested_formats=sound_bible.output_formats,
                selected_model=voice_bible.model,
                reference_voice=voice_bible.narrator_reference_voice,
            )
            preflight_errors = [i for i in preflight_issues if i.severity == "error"]
            if preflight_errors:
                err_msg = "; ".join(i.message for i in preflight_errors)
                ep.status = EpisodeStatus.FAILED
                ep.error = {"message": f"Preflight failed: {err_msg}", "code": "PREFLIGHT_FAILED"}
                self.store.save_episode(ep)
                evt_store.append_project_event(ProductionEvent(
                    project_id=ep.project_id,
                    series_id=series_id,
                    episode_id=ep.episode_id,
                    event_type=ProductionEventType.STEP_FAILED,
                    message=f"Episode '{ep.title}' preflight check failed: {err_msg}",
                ))
                return {"episode_id": ep.episode_id, "status": "failed", "error": ep.error}

            ep.status = EpisodeStatus.PRODUCING
            self.store.save_episode(ep)

            evt_store.append_project_event(ProductionEvent(
                project_id=ep.project_id,
                series_id=series_id,
                episode_id=ep.episode_id,
                event_type=ProductionEventType.WORKFLOW_STARTED,
                message=f"Episode '{ep.title}' workflow execution started.",
            ))

            try:
                # Load project source script
                state = proj_store.get_project_state(ep.project_id)
                script_text = proj_store.read_source_script(ep.project_id)

                # Run or resume workflow
                wf = wf_service.start_workflow(
                    script_text=script_text,
                    project_id=ep.project_id,
                    title=ep.title,
                    language=voice_bible.language or series.language,
                    policy=policy,
                )
                ep.workflow_id = wf.workflow_id
                self.store.save_episode(ep)

                # Wait for workflow completion or human action
                while True:
                    if token.is_cancelled():
                        wf_service.cancel_workflow(wf.workflow_id)

                    st = wf_service.get_workflow(wf.workflow_id)
                    if not st:
                        break

                    if st.status == "waiting_for_human" or getattr(st.status, "value", str(st.status)) == "waiting_for_human":
                        ep.status = EpisodeStatus.WAITING_FOR_HUMAN
                        ep.review_required = True
                        self.store.save_episode(ep)
                        evt_store.append_project_event(ProductionEvent(
                            project_id=ep.project_id,
                            series_id=series_id,
                            episode_id=ep.episode_id,
                            event_type=ProductionEventType.HUMAN_ACTION_REQUIRED,
                            message=f"Episode '{ep.title}' requires human approval/review.",
                        ))
                        return {"episode_id": ep.episode_id, "status": "waiting_for_human"}

                    if st.status == "completed" or getattr(st.status, "value", str(st.status)) == "completed":
                        if token.is_cancelled():
                            ep.status = EpisodeStatus.CANCELLED
                            self.store.save_episode(ep)
                            evt_store.append_project_event(ProductionEvent(
                                project_id=ep.project_id, series_id=series_id, episode_id=ep.episode_id,
                                event_type=ProductionEventType.WORKFLOW_CANCELLED,
                                message=f"Episode '{ep.title}' publish cancelled after workflow completion.",
                            ))
                            return {"episode_id": ep.episode_id, "status": "cancelled"}
                        copied = self._package_episode_deliverables(series, ep, exp_root, token)
                        ep.status = EpisodeStatus.COMPLETED
                        ep.published_at = datetime.now(timezone.utc).isoformat()
                        ep.final_artifacts = copied
                        self.store.save_episode(ep)
                        evt_store.append_project_event(ProductionEvent(
                            project_id=ep.project_id,
                            series_id=series_id,
                            episode_id=ep.episode_id,
                            event_type=ProductionEventType.EXPORT_COMPLETED,
                            message=f"Episode '{ep.title}' production and export completed successfully.",
                        ))
                        return {"episode_id": ep.episode_id, "status": "completed"}

                    if st.status in ("failed", "cancelled", "interrupted") or getattr(st.status, "value", str(st.status)) in ("failed", "cancelled", "interrupted"):
                        terminal_status = getattr(st.status, "value", str(st.status))
                        ep.status = EpisodeStatus.CANCELLED if terminal_status == "cancelled" else EpisodeStatus.FAILED
                        ep.error = st.error
                        self.store.save_episode(ep)
                        evt_store.append_project_event(ProductionEvent(
                            project_id=ep.project_id,
                            series_id=series_id,
                            episode_id=ep.episode_id,
                            event_type=(ProductionEventType.WORKFLOW_CANCELLED
                                        if terminal_status == "cancelled"
                                        else ProductionEventType.STEP_FAILED),
                            message=f"Episode '{ep.title}' workflow ended with status: {ep.status.value}",
                        ))
                        return {"episode_id": ep.episode_id, "status": ep.status.value, "error": st.error}

                    import time
                    time.sleep(0.05)

                ep.status = EpisodeStatus.FAILED
                self.store.save_episode(ep)
                return {"episode_id": ep.episode_id, "status": "failed", "error": "Workflow ended unexpectedly"}

            except SeriesPublishCancelled:
                ep.status = EpisodeStatus.CANCELLED
                self.store.save_episode(ep)
                evt_store.append_project_event(ProductionEvent(
                    project_id=ep.project_id, series_id=series_id, episode_id=ep.episode_id,
                    event_type=ProductionEventType.WORKFLOW_CANCELLED,
                    message=f"Episode '{ep.title}' publish cancelled after workflow completion.",
                ))
                return {"episode_id": ep.episode_id, "status": "cancelled"}
            except Exception as exc:
                ep.status = EpisodeStatus.FAILED
                ep.error = {"message": str(exc)}
                self.store.save_episode(ep)
                evt_store.append_project_event(ProductionEvent(
                    project_id=ep.project_id,
                    series_id=series_id,
                    episode_id=ep.episode_id,
                    event_type=ProductionEventType.STEP_FAILED,
                    message=f"Episode '{ep.title}' error: {exc}",
                ))
                return {"episode_id": ep.episode_id, "status": "failed", "error": str(exc)}

        results = []
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_ep = {executor.submit(produce_single_episode, ep): ep for ep in target_episodes}
                for future in concurrent.futures.as_completed(future_to_ep):
                    try:
                        res = future.result()
                        results.append(res)
                    except Exception as exc:
                        ep = future_to_ep[future]
                        results.append({"episode_id": ep.episode_id, "status": "failed", "error": str(exc)})
                    if progress_callback:
                        progress_callback(
                            "series_production",
                            len(results) / len(target_episodes) * 100.0,
                            {"completed_episodes": len(results), "total_episodes": len(target_episodes)},
                        )
            self._write_series_manifests(series, exp_root)
        finally:
            with _tokens_lock:
                _active_series_tokens.pop(series_id, None)

        # Aggregate counts
        target_ids = {episode.episode_id for episode in target_episodes}
        ep_states = [episode for episode in self.store.list_episodes(series_id) if episode.episode_id in target_ids]
        completed_count = sum(1 for e in ep_states if e.status == EpisodeStatus.COMPLETED)
        failed_count = sum(1 for e in ep_states if e.status == EpisodeStatus.FAILED)
        waiting_count = sum(1 for e in ep_states if e.status == EpisodeStatus.WAITING_FOR_HUMAN)
        cancelled_count = sum(1 for e in ep_states if e.status == EpisodeStatus.CANCELLED)
        running_count = sum(1 for e in ep_states if e.status == EpisodeStatus.PRODUCING)
        queued_count = sum(1 for e in ep_states if e.status in (EpisodeStatus.PENDING, EpisodeStatus.QUEUED))

        total = len(ep_states)
        progress = (completed_count / total * 100.0) if total > 0 else 0.0

        human_actions = self.service.get_review_queue(series_id)

        # The series is complete only when every episode, not merely the requested subset, is complete.
        all_current_episodes = self.store.list_episodes(series_id)
        if all_current_episodes and all(e.status == EpisodeStatus.COMPLETED for e in all_current_episodes):
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
