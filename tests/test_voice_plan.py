"""Unit tests for VoicePlan models, validation rules, YAML serialization, and builder mapper."""

from __future__ import annotations

import unittest
from pydantic import ValidationError

from services.voice_plan import (
    BeatRole,
    SFXPlacement,
    EmphasisStrength,
    ProjectMetadata,
    VoiceMetadata,
    GlobalDirection,
    BeatScript,
    Emphasis,
    PauseModel,
    VoiceDirection,
    AmbienceIntent,
    SFXIntent,
    SilenceAfter,
    SilenceDecision,
    Beat,
    VoicePlan,
    build_voice_plan,
)


class VoicePlanTestCase(unittest.TestCase):
    def test_valid_voice_plan_and_yaml_roundtrip(self):
        # 1. Construct valid plan manually
        proj_meta = ProjectMetadata(
            id="test_proj",
            title="Test Project Title",
            language="en-US",
            source_script="This is a test script text."
        )
        voice_meta = VoiceMetadata(
            profile="narrator_profile",
            provider="gemini",
            model="gemini-3.1-flash-tts-preview"
        )
        global_dir = GlobalDirection(
            tone="mysterious_cinematic",
            base_pace=0.92,
            dramatic_level=3,
            max_energy=5.0,
            avoid_overacting=True
        )
        script_seg = BeatScript(
            text="This is a single storytelling beat.",
            preserve_exact_text=True
        )
        pause_model = PauseModel(before=0.1, after=0.8)
        voice_dir = VoiceDirection(
            emotion="mysterious",
            energy=2.5,
            pace=0.9,
            target_wpm=138,
            volume="normal",
            emphasis=[
                Emphasis(text="mysterious", strength=EmphasisStrength.MEDIUM)
            ],
            pause=pause_model,
            director_note="Keep voice low",
            pronunciation={"Word": "Phonetic"}
        )
        ambience = AmbienceIntent(intent="dark_wind", intensity="medium", volume_db=-29.0)
        sfx = [
            SFXIntent(
                intent="cinematic_riser",
                placement=SFXPlacement.PRE,
                anchor="mysterious",
                offset=0.2,
                intensity="high",
                necessity=0.85,
                max_volume_db=-24.0
            )
        ]
        silence = SilenceDecision(
            after=SilenceAfter(duration=0.5, reason="dramatic pause")
        )
        beat = Beat(
            id="B01",
            role=BeatRole.HOOK,
            script=script_seg,
            voice=voice_dir,
            ambience=ambience,
            sfx=sfx,
            silence=silence
        )
        
        plan = VoicePlan(
            version=1,
            project=proj_meta,
            voice=voice_meta,
            global_direction=global_dir,
            beats=[beat]
        )

        # 2. Verify values
        self.assertEqual(plan.beats[0].id, "B01")
        self.assertEqual(plan.beats[0].role, BeatRole.HOOK)
        self.assertEqual(plan.beats[0].voice.energy, 2.5)
        self.assertEqual(plan.beats[0].script.text, "This is a single storytelling beat.")

        # 3. YAML Roundtrip
        yaml_str = plan.to_yaml()
        self.assertIn("version: 1", yaml_str)
        self.assertIn("mysterious_cinematic", yaml_str)
        
        reconstructed = VoicePlan.from_yaml(yaml_str)
        self.assertEqual(reconstructed.version, plan.version)
        self.assertEqual(reconstructed.project.id, plan.project.id)
        self.assertEqual(reconstructed.beats[0].id, plan.beats[0].id)
        self.assertEqual(reconstructed.beats[0].script.text, plan.beats[0].script.text)
        self.assertEqual(reconstructed.beats[0].voice.pause.before, 0.1)
        self.assertEqual(reconstructed.beats[0].voice.pause.after, 0.8)
        self.assertEqual(reconstructed.beats[0].sfx[0].necessity, 0.85)

    def test_validation_errors(self):
        # Negative pause should fail
        with self.assertRaises(ValidationError):
            PauseModel(before=-0.5, after=0.0)

        with self.assertRaises(ValidationError):
            PauseModel(before=0.0, after=-1.2)

        # SFX necessity outside range [0.0, 1.0] should fail
        with self.assertRaises(ValidationError):
            SFXIntent(intent="riser", placement=SFXPlacement.PRE, necessity=-0.1)
            
        with self.assertRaises(ValidationError):
            SFXIntent(intent="riser", placement=SFXPlacement.PRE, necessity=1.05)

        # Empty script text should fail
        with self.assertRaises(ValidationError):
            BeatScript(text="")

        with self.assertRaises(ValidationError):
            BeatScript(text="   ")

        # Energy outside range [0.0, 5.0] should fail
        with self.assertRaises(ValidationError):
            PauseModelInstance = PauseModel(before=0.0, after=0.0)
            VoiceDirection(
                emotion="mysterious",
                energy=-0.1,
                pace=1.0,
                pause=PauseModelInstance
            )

        with self.assertRaises(ValidationError):
            PauseModelInstance = PauseModel(before=0.0, after=0.0)
            VoiceDirection(
                emotion="mysterious",
                energy=5.2,
                pace=1.0,
                pause=PauseModelInstance
            )

        # Invalid Enum roles or placements should fail
        with self.assertRaises(ValidationError):
            ScriptSegmentInstance = BeatScript(text="Valid text")
            PauseModelInstance = PauseModel(before=0.0, after=0.0)
            VoiceDirectionInstance = VoiceDirection(
                emotion="mysterious",
                energy=2.0,
                pace=1.0,
                pause=PauseModelInstance
            )
            Beat(
                id="B01",
                role="invalid_role_name",  # type: ignore
                script=ScriptSegmentInstance,
                voice=VoiceDirectionInstance
            )

    def test_exact_script_preservation(self):
        raw = "  What if I told you...\n"
        self.assertEqual(BeatScript(text=raw).text, raw)

    def test_compatibility_builder_energy_scaling(self):
        project_data = {
            "id": "proj_12345",
            "topic": "Zhulong Legendary Tale",
            "requirements": {
                "language_id": "en-US",
                "character_id": "char_male_en",
                "default_model": "turbo"
            }
        }
        
        # We test energy values mapping: 0.0 -> 0.0, 0.35 -> 1.75, 0.60 -> 3.0, 1.0 -> 5.0
        energy_test_cases = [
            (0.0, 0.0),
            (0.35, 1.75),
            (0.60, 3.00),
            (1.0, 5.00),
        ]
        
        for input_energy, expected_energy in energy_test_cases:
            segments = [
                {
                    "id": "seg_001",
                    "text": "Valid script line.",
                    "narration_plan": {
                        "role": "narrator",
                        "emotion": "mysterious",
                        "energy": input_energy,
                        "target_wpm": 138,
                        "pause_before_ms": 200,
                        "pause_after_ms": 800,
                        "emphasis": [],
                        "pronunciation": {}
                    }
                }
            ]
            voice_plan = build_voice_plan(project_data, segments)
            beat = voice_plan.beats[0]
            self.assertAlmostEqual(beat.voice.energy, expected_energy, places=2)

    def test_compatibility_builder_mapping(self):
        project_data = {
            "id": "proj_12345",
            "topic": "Zhulong Legendary Tale",
            "requirements": {
                "language_id": "en-US",
                "character_id": "char_male_en",
                "default_model": "turbo"
            }
        }
        
        segments = [
            {
                "id": "seg_001",
                "text": "Its name was Zhulong — the Torch Dragon.",
                "beat_role": "hook",  # Explicitly supplied beat_role
                "narration_plan": {
                    "role": "narrator",
                    "emotion": "mysterious",
                    "energy": 0.8,
                    "target_wpm": 110,
                    "pace": "slow",  # Non-float pace, should map voice.pace = None
                    "pause_before_ms": 200,
                    "pause_after_ms": 1200,
                    "emphasis": ["Zhulong", "Torch Dragon"],
                    "pronunciation": {"Zhulong": "Joo-long"}
                }
            },
            {
                "id": "seg_002",
                "text": "Next sentence is here.",
                # No beat_role supplied, should fallback to default_beat_role (DESCRIPTION)
                "narration_plan": {
                    "role": "narrator",
                    "emotion": "thoughtful",
                    "energy": 0.6,
                    "target_wpm": 138,
                    "pause_before_ms": 100,
                    "pause_after_ms": 700,
                    "emphasis": [],
                    "pronunciation": {}
                }
            }
        ]

        voice_plan = build_voice_plan(project_data, segments, default_beat_role=BeatRole.DESCRIPTION)

        # Verify fallback role and explicit mapping
        self.assertEqual(voice_plan.beats[0].role, BeatRole.HOOK)
        self.assertEqual(voice_plan.beats[1].role, BeatRole.DESCRIPTION)

        # Verify WPM & Pace are preserved according to user feedback
        self.assertEqual(voice_plan.beats[0].voice.target_wpm, 110)
        self.assertIsNone(voice_plan.beats[0].voice.pace)
        
        # Verify pause and timing conversions
        self.assertEqual(voice_plan.beats[0].voice.pause.before, 0.2)
        self.assertEqual(voice_plan.beats[0].voice.pause.after, 1.2)
        self.assertEqual(voice_plan.beats[0].voice.pronunciation, {"Zhulong": "Joo-long"})
        
        # Verify silence decision is None (Phase 1 does not infer silence)
        self.assertIsNone(voice_plan.beats[0].silence)
        
        # Verify emphasis
        self.assertEqual(len(voice_plan.beats[0].voice.emphasis), 2)
        self.assertEqual(voice_plan.beats[0].voice.emphasis[0].text, "Zhulong")
        self.assertEqual(voice_plan.beats[0].voice.emphasis[0].strength, EmphasisStrength.MEDIUM)

    def test_compatibility_builder_fail_fast_role(self):
        project_data = {"id": "proj_123"}
        segments = [
            {
                "id": "seg_001",
                "text": "Valid text",
                "beat_role": "invalid_role_here",
                "narration_plan": {}
            }
        ]
        with self.assertRaises(ValueError):
            build_voice_plan(project_data, segments)
