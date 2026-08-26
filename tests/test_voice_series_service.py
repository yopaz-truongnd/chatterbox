"""Unit tests for VoiceSeriesService (Phase 19)."""

from pathlib import Path
import tempfile
import unittest

from services.voice_project_models import InvalidProjectStateError, VoiceProjectNotFound
from services.voice_series_models import (
    EpisodeStatus,
    SeriesPronunciationBible,
    SeriesVoiceBible,
    VoiceSeries,
    VoiceSeriesEpisode,
)
from services.voice_series_service import VoiceSeriesService
from services.voice_series_store import VoiceSeriesStore


class TestVoiceSeriesService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = VoiceSeriesStore(root_dir=Path(self.tmp.name) / "series")
        self.service = VoiceSeriesService(store=self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_and_get_series(self):
        series = self.service.create_series(
            title="Tales of Olympus",
            description="Greek mythology audio stories",
            voice_bible=SeriesVoiceBible(narrator_character="homer", provider="fake"),
        )
        self.assertIsNotNone(series.series_id)
        self.assertEqual(series.title, "Tales of Olympus")

        fetched = self.service.get_series(series.series_id)
        self.assertEqual(fetched.title, "Tales of Olympus")
        self.assertEqual(fetched.voice_bible.narrator_character, "homer")

    def test_add_episodes_and_maintain_order(self):
        series = self.service.create_series(title="Norse Legends")

        ep1 = self.service.add_episode(series.series_id, project_id="proj_thor", title="Thor's Hammer")
        ep2 = self.service.add_episode(series.series_id, project_id="proj_loki", title="Loki's Trick")

        self.assertEqual(ep1.episode_number, 1)
        self.assertEqual(ep2.episode_number, 2)

        episodes = self.service.list_episodes(series.series_id)
        self.assertEqual(len(episodes), 2)
        self.assertEqual(episodes[0].title, "Thor's Hammer")
        self.assertEqual(episodes[1].title, "Loki's Trick")

    def test_update_series_does_not_mutate_completed_episodes(self):
        series = self.service.create_series(
            title="Egyptian Pantheon",
            voice_bible=SeriesVoiceBible(narrator_character="ra_priest", provider="fake"),
        )
        ep = self.service.add_episode(series.series_id, project_id="proj_osiris", title="Osiris Legend")

        # Mark episode as completed
        ep.status = EpisodeStatus.COMPLETED
        self.store.save_episode(ep)

        # Update series narrator to anubis_scribe
        self.service.update_series(
            series.series_id,
            {"voice_bible": {"narrator_character": "anubis_scribe", "provider": "fake"}},
        )

        # Confirm completed episode remains untouched
        ep_after = self.service.get_episode(series.series_id, ep.episode_id)
        self.assertEqual(ep_after.status, EpisodeStatus.COMPLETED)
        self.assertEqual(ep_after.title, "Osiris Legend")
