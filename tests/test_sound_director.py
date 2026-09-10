"""Unit tests for Sound Director (Phase 3), Director Critic, and End-to-End Planning pipeline."""

from __future__ import annotations

import unittest
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
    SFXIntent,
    SFXFunction,
    Beat,
    VoicePlan,
    build_voice_plan,
)
from services.sound_director import (
    direct_sound,
    classify_sfx_prominence,
    load_sound_policy,
)
from services.director_critic import (
    critique_voice_plan,
    apply_director_fixes,
    calculate_sfx_timestamps,
)
from services.story_analyzer import (
    analyze_story_beats,
    story_beats_to_narration_segments,
)
from services.narration_planner import compile_narration_plan


class SoundDirectorTestCase(unittest.TestCase):
    def test_sfx_necessity_prominence_classification(self):
        self.assertEqual(classify_sfx_prominence(0.85), "prominent")
        self.assertEqual(classify_sfx_prominence(0.70), "light")
        self.assertEqual(classify_sfx_prominence(0.50), "subtle")
        self.assertEqual(classify_sfx_prominence(0.35), "removed")

    def test_reflection_beat_blocks_emphasis_sfx(self):
        # Construct reflection beat plan
        proj_meta = ProjectMetadata(id="proj", title="Test", source_script="Text")
        voice_meta = VoiceMetadata(profile="p", provider="g", model="m")
        global_dir = GlobalDirection(tone="m", base_pace=0.92, dramatic_level=3, max_energy=5.0, avoid_overacting=True)
        
        # Beat has REFLECTION role and has emphasis SFX
        beat = Beat(
            id="B01",
            role=BeatRole.REFLECTION,
            script=BeatScript(text="Perhaps Zhulong was never merely a creature."),
            voice=VoiceDirection(
                emotion="thoughtful", energy=2.0, pace=1.0,
                pause=PauseModel(before=0.0, after=1.5)
            ),
            sfx=[
                SFXIntent(
                    intent="subtle_boom",
                    function=SFXFunction.EMPHASIS,
                    placement=SFXPlacement.POST,
                    necessity=0.85
                )
            ]
        )
        plan = VoicePlan(project=proj_meta, voice=voice_meta, global_direction=global_dir, beats=[beat])
        
        # Critique before fix should detect issue
        critique = critique_voice_plan(plan)
        self.assertTrue(any("Forbidden prominent/emphasis" in issue for issue in critique.issues))

        # Auto-fix should strip the forbidden emphasis SFX
        fixed_plan = apply_director_fixes(plan, critique)
        self.assertEqual(len(fixed_plan.beats[0].sfx), 0)

        # Check non-mutability of input plan
        self.assertEqual(len(plan.beats[0].sfx), 1)

    def test_density_and_gap_conflicts_autofix_priority(self):
        # Group with gap conflict: Beat 1 and Beat 2 both have prominent SFX with 2 seconds gap
        proj_meta = ProjectMetadata(id="proj", title="Test", source_script="Text")
        voice_meta = VoiceMetadata(profile="p", provider="g", model="m")
        global_dir = GlobalDirection(tone="m", base_pace=0.92, dramatic_level=3, max_energy=5.0, avoid_overacting=True)

        # Beat 1 is REVEAL, has riser SFX (necessity 0.85)
        beat1 = Beat(
            id="B01",
            role=BeatRole.REVEAL,
            script=BeatScript(text="Its name was Zhulong."),
            voice=VoiceDirection(
                emotion="mysterious", energy=3.0, pace=1.0,
                pause=PauseModel(before=0.0, after=0.5) # beat dur estimated ~ 2s + 0.5s pause = 2.5s end
            ),
            sfx=[
                SFXIntent(
                    intent="reveal_riser",
                    function=SFXFunction.TRANSITION,
                    placement=SFXPlacement.POST,
                    necessity=0.85
                )
            ]
        )
        # Beat 2 is CLIMAX, starts at 2.5s, has impact SFX (necessity 0.82)
        beat2 = Beat(
            id="B02",
            role=BeatRole.CLIMAX,
            script=BeatScript(text="It was a clash of cosmic forces."),
            voice=VoiceDirection(
                emotion="dramatic", energy=4.5, pace=1.0,
                pause=PauseModel(before=0.0, after=0.5)
            ),
            sfx=[
                SFXIntent(
                    intent="climax_impact",
                    function=SFXFunction.EMPHASIS,
                    placement=SFXPlacement.PRE, # timestamp = 2.5s start
                    necessity=0.82
                )
            ]
        )
        plan = VoicePlan(project=proj_meta, voice=voice_meta, global_direction=global_dir, beats=[beat1, beat2])

        # Verify gap is 2.5s - 2.5s = 0s < 5s gap
        critique = critique_voice_plan(plan)
        self.assertTrue(any("SFX Gap Conflict" in issue for issue in critique.issues))

        # Auto-fix: Compare composite score
        # beat1 (REVEAL): necessity 0.85 + role_bonus 0.0 = 0.85
        # beat2 (CLIMAX): necessity 0.82 + role_bonus 0.50 = 1.32
        # Climax beat has higher priority and should be preserved! Riser on beat1 should be discarded!
        fixed = apply_director_fixes(plan, critique)
        
        self.assertEqual(len(fixed.beats[0].sfx), 0) # reveal sfx removed
        self.assertEqual(len(fixed.beats[1].sfx), 1) # climax sfx preserved!
        self.assertEqual(fixed.beats[1].sfx[0].intent, "climax_impact")

    def test_end_to_end_planning_pipeline(self):
        raw_script = (
            "What if I told you that, in ancient Chinese mythology, "
            "there was a dragon so powerful... simply opening its eyes could bring daylight to the world?\n\n"
            "Its name was Zhulong — the Torch Dragon. Zhulong appears in ancient Chinese texts.\n\n"
            "When Zhulong opened its eyes... it was day. When it closed them... night fell.\n\n"
            "Perhaps Zhulong was never merely a creature."
        )

        project_data = {
            "id": "proj_torch_dragon",
            "topic": "Zhulong Legendary Narrative",
            "requirements": {
                "language_id": "en-US",
                "character_id": "char_narrator_en",
                "default_model": "turbo"
            }
        }

        # 1. Story Analyzer groups text and classifies roles
        story_beats = analyze_story_beats(raw_script)
        self.assertEqual(len(story_beats), 4)
        self.assertEqual(story_beats[0].id, "B01")
        self.assertEqual(story_beats[0].role, BeatRole.HOOK)
        self.assertEqual(story_beats[3].role, BeatRole.REFLECTION)

        # 2. Adapter converts to Narration segments
        segments = story_beats_to_narration_segments(story_beats)
        self.assertEqual(len(segments), 4)
        self.assertEqual(segments[0]["id"], "B01")
        self.assertEqual(segments[0]["beat_role"], "hook")

        # 3. Narration Planner compiles direction
        planned_segments = compile_narration_plan(segments)

        # 4. Build Voice Plan (Phase 1 Builder)
        voice_plan = build_voice_plan(project_data, planned_segments)
        self.assertEqual(voice_plan.project.id, "proj_torch_dragon")
        self.assertEqual(voice_plan.beats[0].id, "B01")
        self.assertEqual(voice_plan.beats[0].role, BeatRole.HOOK)

        # 5. Sound Director adds decisions
        directed_plan = direct_sound(voice_plan)
        
        # Verify direct_sound did not mutate original voice_plan (non-mutating check)
        self.assertIsNot(directed_plan, voice_plan)
        self.assertIsNone(voice_plan.beats[0].ambience)

        # Verify hook has ambience intent
        self.assertIsNotNone(directed_plan.beats[0].ambience)
        # Verify reflection beat has silence decision
        self.assertIsNotNone(directed_plan.beats[3].silence)

        # 6. Critique and Autofix
        critique = critique_voice_plan(directed_plan)
        fixed_plan = apply_director_fixes(directed_plan, critique)

        # Invariant validations
        # Exact text preservation: Verify each beat matches its source offsets
        for idx, beat in enumerate(fixed_plan.beats):
            self.assertEqual(beat.script.text, raw_script[story_beats[idx].source_start:story_beats[idx].source_end])

        # Exact byte-for-byte reconstruction of original raw script text
        reconstructed = raw_script[story_beats[0].source_start:story_beats[-1].source_end]
        self.assertEqual(reconstructed, raw_script)

        # IDs and roles unchanged
        for idx, beat in enumerate(fixed_plan.beats):
            self.assertEqual(beat.id, story_beats[idx].id)
            self.assertEqual(beat.role, story_beats[idx].role)

    def test_load_sound_policy_no_global_default_mutation(self):
        import copy
        import tempfile
        from services.sound_director import DEFAULT_SOUND_POLICY

        original_policy = copy.deepcopy(DEFAULT_SOUND_POLICY)

        custom_policy_yaml = (
            "version: 2\n"
            "general:\n"
            "  voice_priority: 999\n"
            "density:\n"
            "  max_prominent_sfx_per_minute: 99\n"
            "roles:\n"
            "  hook:\n"
            "    ambience: custom_preferred\n"
        )

        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tf:
            tf.write(custom_policy_yaml)
            tf_path = tf.name

        try:
            loaded = load_sound_policy(tf_path)
            self.assertEqual(loaded["general"]["voice_priority"], 999)
            self.assertEqual(loaded["density"]["max_prominent_sfx_per_minute"], 99)
            self.assertEqual(loaded["roles"]["hook"]["ambience"], "custom_preferred")

            # Assert DEFAULT_SOUND_POLICY was NOT mutated
            self.assertEqual(DEFAULT_SOUND_POLICY, original_policy)
            self.assertEqual(DEFAULT_SOUND_POLICY["general"]["voice_priority"], 100)
            self.assertEqual(DEFAULT_SOUND_POLICY["density"]["max_prominent_sfx_per_minute"], 5)
            self.assertEqual(DEFAULT_SOUND_POLICY["roles"]["hook"]["ambience"], "preferred")

            # Call loader without override and assert clean defaults
            pristine = load_sound_policy(policy_path="/non/existent/sound-director.yaml")
            self.assertEqual(pristine["general"]["voice_priority"], 100)
        finally:
            import os
            if os.path.exists(tf_path):
                os.unlink(tf_path)


if __name__ == "__main__":
    unittest.main()
