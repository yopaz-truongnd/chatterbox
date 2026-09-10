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
        
        # Verify each beat's text matches its exact source span
        for beat in beats:
            self.assertEqual(beat.text, script_text[beat.source_start:beat.source_end])

        # Verify exact reconstruction using spans matches original script_text 100% byte-for-byte
        reconstructed = script_text[beats[0].source_start:beats[-1].source_end]
        self.assertEqual(reconstructed, script_text)

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

    def test_lore_with_mythological_keywords(self):
        # Contains "dragon" but also "ancient texts" and exposition. Should be classified as LORE, not SUPERNATURAL_EVENT.
        script_text = "Ancient texts describe the crimson dragon dwelling beyond the northern wilderness."
        from services.story_analyzer import classify_beat_role
        role, _ = classify_beat_role(script_text, [{"text": script_text}], beat_idx=2)
        self.assertEqual(role, BeatRole.LORE)

    def test_unresolved_source_span_fails_fast(self):
        script = "Original sentence."
        segments = [{"text": "Modified sentence."}]
        with self.assertRaises(ValueError):
            analyze_story_beats(script, segments)

    def test_final_descriptive_beat_remains_description(self):
        # Even if it is in final position, if there are no concluding signals, it remains DESCRIPTION
        script_text = "Zhulong's body was red and thousands of miles long."
        from services.story_analyzer import classify_beat_role
        role, _ = classify_beat_role(script_text, [{"text": script_text}], beat_idx=3)
        self.assertEqual(role, BeatRole.DESCRIPTION)

    def test_outro_concluding_signals_classified_correctly(self):
        # Concluding signals should correctly resolve to OUTRO
        script_text = "Finally, the tale concludes our lesson about the rhythm of the cosmos."
        from services.story_analyzer import classify_beat_role
        role, _ = classify_beat_role(script_text, [{"text": script_text}], beat_idx=3)
        self.assertEqual(role, BeatRole.OUTRO)
