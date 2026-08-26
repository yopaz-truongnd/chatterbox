"""Recovery, cancellation, and human review gate tests for Series (Phase 19)."""

import os
from pathlib import Path
import tempfile
import unittest

from services.voice_project_operations import CancellationToken
from services.voice_project_service import VoiceProjectService
from services.voice_project_store import VoiceProjectStore
from services.voice_series_models import (
    EpisodeStatus,
    SeriesProductionPolicy,
    SeriesVoiceBible,
)
from services.voice_series_operations import VoiceSeriesOperations
from services.voice_series_service import VoiceSeriesService
from services.voice_series_store import VoiceSeriesStore
from services.voice_project_workflow import VoiceProjectWorkflowService
from services.voice_project_workflow_store import VoiceProjectWorkflowStore
from services.tts.fake import FakeTTSProvider


class TestVoiceSeriesRecovery(unittest.TestCase):
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

    def test_cancellation_does_not_publish_pending_audio(self):
        series = self.series_service.create_series(
            title="Cancelled Voyage",
            voice_bible=SeriesVoiceBible(provider="fake"),
        )
        self.proj_service.create_project("The ship sailed into the misty horizon.", project_id="proj_cancel")
        ep = self.series_service.add_episode(series.series_id, "proj_cancel", "Misty Horizon", 1)

        token = CancellationToken()
        token.cancel()  # already cancelled before start

        exp_dir = Path(self.tmp.name) / "exports"
        summary = self.series_ops.produce_series(
            series.series_id,
            cancellation_token=token,
            export_root=exp_dir,
        )

        self.assertEqual(summary.cancelled, 1)
        self.assertFalse((exp_dir / series.slug / "episode-001" / "FINAL.wav").exists())

    def test_completed_episode_is_not_rerun_on_subsequent_produce(self):
        series = self.series_service.create_series(
            title="Two Kingdoms",
            voice_bible=SeriesVoiceBible(provider="fake"),
        )
        self.proj_service.create_project("The kingdom in the west flourished.", project_id="proj_k1")
        self.proj_service.create_project("The kingdom in the east defended its borders.", project_id="proj_k2")

        ep1 = self.series_service.add_episode(series.series_id, "proj_k1", "West Kingdom", 1)
        ep2 = self.series_service.add_episode(series.series_id, "proj_k2", "East Kingdom", 2)

        exp_dir = Path(self.tmp.name) / "exports"

        # Produce only ep1 first
        s1 = self.series_ops.produce_series(series.series_id, episode_ids=[ep1.episode_id], export_root=exp_dir)
        self.assertEqual(s1.completed, 1)

        ep1_state = self.series_service.get_episode(series.series_id, ep1.episode_id)
        self.assertEqual(ep1_state.status, EpisodeStatus.COMPLETED)
        ep1_pub = ep1_state.published_at

        # Produce whole series; ep1 must be skipped/preserved without changing published_at
        s2 = self.series_ops.produce_series(series.series_id, export_root=exp_dir)
        self.assertEqual(s2.completed, 2)

        ep1_state_after = self.series_service.get_episode(series.series_id, ep1.episode_id)
        self.assertEqual(ep1_state_after.published_at, ep1_pub)
