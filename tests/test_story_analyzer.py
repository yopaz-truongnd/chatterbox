"""Unit tests for Phase 2 Story Analyzer, semantic beat grouping, and lineage tracking."""

from __future__ import annotations

import unittest
from services.voice_plan import BeatRole
from services.story_analyzer import (
    StoryBeat,
    analyze_story_beats,
    story_beats_to_narration_segments,
)


class StoryAnalyzerTestCase(unittest.TestCase):
    def test_exact_text_preservation_with_whitespaces(self):
        script_text = "  What if I told you...\n\nIts name was Zhulong — the Torch Dragon.  "
        beats = analyze_story_beats(script_text)
        
        # Verify exact reconstruction matches original text
        reconstructed = " ".join(beat.text for beat in beats)
        self.assertEqual(reconstructed, "  What if I told you... Its name was Zhulong — the Torch Dragon.  ")

        # Lineage check
        self.assertIsNotNone(beats[0].source_start)
        self.assertIsNotNone(beats[0].source_end)

    def test_multi_sentence_grouping_and_ids(self):
        # We supply segments representing multiple short sentences
        script_text = "One sentence. Two sentence. Three sentence."
        segments = [
            {"id": "seg_001", "text": "One sentence.", "estimated_seconds": 2.0},
            {"id": "seg_002", "text": "Two sentence.", "estimated_seconds": 2.0},
            {"id": "seg_003", "text": "Three sentence.", "estimated_seconds": 2.0},
        ]
        
        beats = analyze_story_beats(script_text, segments)
        # Should be grouped into a single beat because total duration (6.0s) is within 25s
        self.assertEqual(len(beats), 1)
        self.assertEqual(beats[0].id, "B01")
        self.assertEqual(beats[0].source_segment_ids, ["seg_001", "seg_002", "seg_003"])

    def test_signal_based_role_classification(self):
        script_text = (
            "What if I told you there was a dragon?\n\n"
            "Ancient texts placed it beyond the northern wilderness.\n\n"
            "The mountain split open as the dragon awoke."
        )
        segments = [
            {"id": "seg_001", "text": "What if I told you there was a dragon?", "estimated_seconds": 5.0},
            {"id": "seg_002", "text": "Ancient texts placed it beyond the northern wilderness.", "estimated_seconds": 8.0},
            {"id": "seg_003", "text": "The mountain split open as the dragon awoke.", "estimated_seconds": 8.0},
        ]
        
        beats = analyze_story_beats(script_text, segments)
        self.assertEqual(len(beats), 3)
        
        # Beat 1: Hook (first position, direct question)
        self.assertEqual(beats[0].role, BeatRole.HOOK)
        
        # Beat 2: Lore (keywords: ancient, wilderness)
        self.assertEqual(beats[1].role, BeatRole.LORE)
        
        # Beat 3: Climax or Supernatural (keywords: split open, awoke)
        self.assertEqual(beats[2].role, BeatRole.SUPERNATURAL_EVENT)

    def test_fail_fast_on_invalid_role(self):
        script_text = "Valid line."
        segments = [
            {
                "id": "seg_001",
                "text": "Valid line.",
                "beat_role": "invalid_role_value",
                "estimated_seconds": 2.0
            }
        ]
        with self.assertRaises(ValueError):
            analyze_story_beats(script_text, segments)

    def test_adapter_mapping(self):
        beats = [
            StoryBeat(
                id="B01",
                role=BeatRole.HOOK,
                text="What if I told you...",
                source_segment_ids=["seg_001"],
                estimated_seconds=4.5,
                confidence=0.9
            )
        ]
        original_segments = [
            {"id": "seg_001", "text": "What if I told you...", "speaker": "Alice", "emotion": "mysterious"}
        ]
        
        mapped = story_beats_to_narration_segments(beats, original_segments)
        self.assertEqual(len(mapped), 1)
        self.assertEqual(mapped[0]["id"], "B01")
        self.assertEqual(mapped[0]["speaker"], "Alice")
        self.assertEqual(mapped[0]["emotion"], "mysterious")
        self.assertEqual(mapped[0]["beat_role"], "hook")
