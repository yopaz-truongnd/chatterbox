"""Unit tests for Voice Series domain models (Phase 19)."""

import unittest
from services.voice_series_models import (
    EpisodeStatus,
    SeriesHumanAction,
    SeriesProductionPolicy,
    SeriesProductionSummary,
    SeriesPronunciationBible,
    SeriesSoundBible,
    SeriesStatus,
    SeriesVoiceBible,
    VoiceSeries,
    VoiceSeriesEpisode,
    make_safe_slug,
)


class TestVoiceSeriesModels(unittest.TestCase):
    def test_safe_slug_generation(self):
        self.assertEqual(make_safe_slug("Journey to the West: Part 1!"), "journey-to-the-west-part-1")
        self.assertEqual(make_safe_slug("  Mythology -- Series #1  "), "mythology-series-1")
        self.assertEqual(make_safe_slug("../../../evil/path"), "evilpath")
        self.assertEqual(make_safe_slug(""), "series")

    def test_voice_series_roundtrip_yaml(self):
        series = VoiceSeries(
            series_id="ser_test_01",
            title="The Nine Dragons",
            description="Legendary tales of ancient dragons",
            voice_bible=SeriesVoiceBible(
                narrator_character="elder_sage",
                provider="fake",
                voice_style="dramatic, epic",
            ),
            pronunciation_bible=SeriesPronunciationBible(
                overrides={"Zhulong": "dzh-oo-long"}
            ),
            sound_bible=SeriesSoundBible(
                mastering_profile="storytelling",
                output_formats=["wav", "mp3"],
            ),
        )

        yaml_str = series.to_yaml()
        loaded = VoiceSeries.from_yaml(yaml_str)

        self.assertEqual(loaded.series_id, series.series_id)
        self.assertEqual(loaded.title, series.title)
        self.assertEqual(loaded.voice_bible.narrator_character, "elder_sage")
        self.assertEqual(loaded.pronunciation_bible.overrides["Zhulong"], "dzh-oo-long")
        self.assertEqual(loaded.slug, "the-nine-dragons")

    def test_episode_model_defaults(self):
        ep = VoiceSeriesEpisode(
            episode_id="ep_01",
            series_id="ser_test_01",
            project_id="proj_01",
            episode_number=1,
            title="Dragon of the North",
        )
        self.assertEqual(ep.status, EpisodeStatus.PENDING)
        self.assertEqual(ep.episode_number, 1)
