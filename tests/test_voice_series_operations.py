"""Integration tests for Batch Series Production operations (Phase 19)."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from services.voice_project_models import InvalidProjectStateError
from services.voice_series_models import (
    EpisodeStatus,
    SeriesProductionPolicy,
    SeriesSoundBible,
    SeriesVoiceBible,
    VoiceSeries,
    VoiceSeriesEpisode,
)
from services.voice_series_operations import VoiceSeriesOperations
from services.voice_series_service import VoiceSeriesService
from services.voice_series_store import VoiceSeriesStore
from services.voice_project_service import VoiceProjectService
from services.voice_project_store import VoiceProjectStore
from services.voice_project_workflow import VoiceProjectWorkflowService
from services.voice_project_workflow_store import VoiceProjectWorkflowStore
from services.tts.fake import FakeTTSProvider


class TestVoiceSeriesOperations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ["CHATTERBOX_API_DATA_DIR"] = str(self.tmp.name)
        os.environ["CHATTERBOX_IN_PROCESS"] = "1"

        self.series_store = VoiceSeriesStore(root_dir=Path(self.tmp.name) / "series")
        self.proj_store = VoiceProjectStore(root_dir=Path(self.tmp.name) / "projects")
        self.wf_store = VoiceProjectWorkflowStore(root_dir=Path(self.tmp.name) / "workflows")
        self.provider = FakeTTSProvider()
        self.proj_service = VoiceProjectService(
            store=self.proj_store,
            execution_port=self.provider,
            provider_name="fake",
        )
        self.wf_service = VoiceProjectWorkflowService(
            store=self.wf_store,
            project_store=self.proj_store,
        )
        self.series_service = VoiceSeriesService(store=self.series_store)
        self.series_ops = VoiceSeriesOperations(
            service=self.series_service,
            store=self.series_store,
            proj_store=self.proj_store,
            proj_service=self.proj_service,
            wf_service=self.wf_service,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _setup_episode_project(self, project_id: str, script: str):
        self.proj_service.create_project(script, project_id=project_id)

    def test_batch_production_runs_episodes_and_aggregates_progress(self):
        series = self.series_service.create_series(
            title="Legends of the Steppe",
            voice_bible=SeriesVoiceBible(provider="fake"),
            sound_bible=SeriesSoundBible(mastering_profile="storytelling", output_formats=["wav"]),
        )

        self._setup_episode_project("proj_ep1", "The golden eagle flew across the blue sky.")
        self._setup_episode_project("proj_ep2", "The great stallion galloped through the tall grass.")

        ep1 = self.series_service.add_episode(series.series_id, "proj_ep1", "The Eagle", 1)
        ep2 = self.series_service.add_episode(series.series_id, "proj_ep2", "The Stallion", 2)

        exp_dir = Path(self.tmp.name) / "exports"
        summary = self.series_ops.produce_series(
            series.series_id,
            export_root=exp_dir,
        )

        self.assertEqual(summary.total_episodes, 2)
        self.assertEqual(summary.completed, 2)
        self.assertEqual(summary.progress_percent, 100.0)

        # Check export packaging
        slug = series.slug
        self.assertTrue((exp_dir / slug / "series-manifest.yaml").exists())
        self.assertTrue((exp_dir / slug / "voice-bible.yaml").exists())
        self.assertTrue((exp_dir / slug / "episode-001" / "FINAL.wav").exists())
        self.assertTrue((exp_dir / slug / "episode-002" / "FINAL.wav").exists())

    def test_failure_in_one_episode_does_not_corrupt_another(self):
        series = self.series_service.create_series(
            title="Trial of Heroes",
            voice_bible=SeriesVoiceBible(provider="fake"),
        )

        self._setup_episode_project("proj_good", "The brave warrior protected the village.")
        # ep2 has no project created on disk -> will fail
        ep_good = self.series_service.add_episode(series.series_id, "proj_good", "Good Hero", 1)
        ep_bad = self.series_service.add_episode(series.series_id, "proj_nonexistent", "Bad Hero", 2)

        summary = self.series_ops.produce_series(
            series.series_id,
            export_root=Path(self.tmp.name) / "exports",
        )

        self.assertEqual(summary.completed, 1)
        self.assertEqual(summary.failed, 1)

        ep1_state = self.series_service.get_episode(series.series_id, ep_good.episode_id)
        ep2_state = self.series_service.get_episode(series.series_id, ep_bad.episode_id)

        self.assertEqual(ep1_state.status, EpisodeStatus.COMPLETED)
        self.assertEqual(ep2_state.status, EpisodeStatus.FAILED)
