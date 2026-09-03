"""Unit tests for Production Health aggregation (Phase 20)."""

from pathlib import Path
import tempfile
import unittest

from services.production_event_models import (
    ProjectProductionHealth,
    SeriesProductionHealth,
)
from services.production_health_service import get_project_health, get_series_health
from services.voice_project_service import VoiceProjectService
from services.voice_project_store import VoiceProjectStore
from services.voice_series_models import SeriesVoiceBible
from services.voice_series_service import VoiceSeriesService
from services.voice_series_store import VoiceSeriesStore
from services.tts.fake import FakeTTSProvider


class TestProductionHealth(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.proj_store = VoiceProjectStore(root_dir=Path(self.tmp.name) / "projects")
        self.series_store = VoiceSeriesStore(root_dir=Path(self.tmp.name) / "series")
        self.provider = FakeTTSProvider()
        self.proj_service = VoiceProjectService(
            store=self.proj_store, execution_port=self.provider, provider_name="fake"
        )
        self.series_service = VoiceSeriesService(store=self.series_store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_project_health_aggregation(self):
        pid = "proj_health_test"
        self.proj_service.create_project("A quiet stream flowed through the mountains.", project_id=pid)
        self.proj_service.plan(pid)

        health = get_project_health(pid, project_store=self.proj_store)
        self.assertIsInstance(health, ProjectProductionHealth)
        self.assertEqual(health.project_id, pid)
        self.assertIn("voice_plan", health.artifact_freshness)

    def test_series_health_aggregation(self):
        series = self.series_service.create_series(title="Epic Chronicle")
        ep1 = self.series_service.add_episode(series.series_id, "proj_ep1", "Chapter 1", 1)

        health = get_series_health(series.series_id, series_store=self.series_store)
        self.assertIsInstance(health, SeriesProductionHealth)
        self.assertEqual(health.series_id, series.series_id)
        self.assertEqual(health.episode_count, 1)
