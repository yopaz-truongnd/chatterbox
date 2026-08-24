"""Unit tests for Phase 4 Resource Manager service."""

import unittest
from services.voice_plan import (
    VoicePlan,
    Beat,
    BeatRole,
    BeatScript,
    VoiceDirection,
    AmbienceIntent,
    SFXIntent,
    SFXFunction,
    SFXPlacement,
    PauseModel,
    ProjectMetadata,
    VoiceMetadata,
    GlobalDirection,
)
from services.resource_models import (
    DesiredProperties,
    NarrativeContext,
    RequirementPriority,
    ResolutionContext,
    ResolutionStatus,
    ResourceCategory,
    ResourceEntry,
    ResourceFile,
    ResourceGap,
    ResourceManifest,
    ResourceMixSettings,
    ResourceProperties,
    ResourceRequirement,
    ResourceResolution,
    ResourceUsage,
)
from services.resource_manager import (
    extract_resource_requirements,
    score_candidate,
    resolve_requirement,
    resolve_project_resources,
    generate_suggested_search,
    load_manifest,
    load_substitution_rules,
    load_selection_rules,
)


class TestResourceManagerPhase4(unittest.TestCase):

    def setUp(self):
        # Build sample manifest
        self.manifest = ResourceManifest(
            version=1,
            resources=[
                ResourceEntry(
                    id="ambience_dark_01",
                    file=ResourceFile(path="ambience/dark/dark_wind_01.wav", format="wav"),
                    category=ResourceCategory.AMBIENCE,
                    intents=["ancient_dark_atmosphere", "mysterious_environment"],
                    tags=["dark", "ancient", "wind", "mysterious"],
                    properties=ResourceProperties(duration=43.2, loopable=True, intensity=2),
                    mix=ResourceMixSettings(recommended_db=-29.0, max_db=-24.0),
                    usage=ResourceUsage(total=0, last_used=None, recent_projects=[]),
                ),
                ResourceEntry(
                    id="ambience_temple_01",
                    file=ResourceFile(path="ambience/ancient/temple_drone_01.wav", format="wav"),
                    category=ResourceCategory.AMBIENCE,
                    intents=["dark_temple_ambience"],
                    tags=["ancient", "temple", "sacred", "mystical"],
                    properties=ResourceProperties(duration=60.0, loopable=True, intensity=3),
                    mix=ResourceMixSettings(recommended_db=-30.0, max_db=-25.0),
                    usage=ResourceUsage(total=0, last_used=None, recent_projects=[]),
                ),
                ResourceEntry(
                    id="sfx_riser_mystical_01",
                    file=ResourceFile(path="sfx/riser/mystical_dark_riser_01.wav", format="wav"),
                    category=ResourceCategory.SFX,
                    intents=["mystical_dark_riser", "dark_tension_riser"],
                    tags=["dark", "mystical", "riser", "cinematic"],
                    properties=ResourceProperties(duration=3.5, loopable=False, intensity=3),
                    mix=ResourceMixSettings(recommended_db=-22.0, max_db=-18.0),
                    usage=ResourceUsage(total=0, last_used=None, recent_projects=[]),
                ),
                ResourceEntry(
                    id="sfx_impact_supernatural_01",
                    file=ResourceFile(path="sfx/impact/supernatural_impact_01.wav", format="wav"),
                    category=ResourceCategory.SFX,
                    intents=["dark_supernatural_impact", "heavy_doom_hit"],
                    tags=["dark", "impact", "supernatural", "heavy"],
                    properties=ResourceProperties(duration=2.8, loopable=False, intensity=5),
                    mix=ResourceMixSettings(recommended_db=-20.0, max_db=-16.0),
                    usage=ResourceUsage(total=5, last_used={"project": "proj_prev", "date": "2026-08-24"}, recent_projects=["proj_prev", "proj_prev", "proj_prev"]),
                ),
            ]
        )

        self.sub_rules = {
            "supernatural_reveal_riser": [
                "mystical_dark_riser",
                "dark_tension_riser",
            ],
            "ancient_dark_atmosphere": [
                "dark_temple_ambience",
            ]
        }

    def test_extract_resource_requirements_from_voice_plan(self):
        plan = VoicePlan(
            version=1,
            project=ProjectMetadata(id="proj_01", title="Torch Dragon", source_script="When Zhulong opened its eyes."),
            voice=VoiceMetadata(profile="mythology_female_v1", provider="gemini", model="flash-tts"),
            global_direction=GlobalDirection(tone="mysterious", base_pace=0.92, dramatic_level=3, max_energy=5.0, avoid_overacting=True),
            beats=[
                Beat(
                    id="B01",
                    role=BeatRole.HOOK,
                    script=BeatScript(text="In the northern extremes beyond the realm of men..."),
                    voice=VoiceDirection(emotion="suspense", energy=2.5, pause=PauseModel(before=0.1, after=0.7)),
                    ambience=AmbienceIntent(intent="ancient_dark_atmosphere", intensity="subtle", volume_db=-29.0),
                    sfx=[],
                ),
                Beat(
                    id="B02",
                    role=BeatRole.SUPERNATURAL_EVENT,
                    script=BeatScript(text="When Zhulong opened its eyes, eternal daylight illuminated the darkness."),
                    voice=VoiceDirection(emotion="dramatic", energy=4.0, pause=PauseModel(before=0.2, after=0.8)),
                    ambience=None,
                    sfx=[
                        SFXIntent(
                            intent="supernatural_reveal_riser",
                            function=SFXFunction.EMPHASIS,
                            placement=SFXPlacement.PRE,
                            intensity="prominent",
                            necessity=0.85,
                        )
                    ],
                )
            ]
        )

        reqs = extract_resource_requirements(plan)
        # Should extract: 1 ambience requirement, 1 sfx requirement (Voice is evaluated at render time)
        self.assertEqual(len(reqs), 2)

        amb_req = next(r for r in reqs if r.type == ResourceCategory.AMBIENCE)
        self.assertEqual(amb_req.priority, RequirementPriority.RECOMMENDED)
        self.assertEqual(amb_req.intent, "ancient_dark_atmosphere")
        self.assertEqual(amb_req.beat_id, "B01")

        sfx_req = next(r for r in reqs if r.type == ResourceCategory.SFX)
        self.assertEqual(sfx_req.priority, RequirementPriority.RECOMMENDED)
        self.assertEqual(sfx_req.intent, "supernatural_reveal_riser")
        self.assertEqual(sfx_req.beat_id, "B02")

    def test_exact_intent_resolution(self):
        req = ResourceRequirement(
            id="REQ_01",
            type=ResourceCategory.AMBIENCE,
            intent="ancient_dark_atmosphere",
            priority=RequirementPriority.RECOMMENDED,
            desired=DesiredProperties(intensity=2, tags=["dark", "ancient"]),
        )
        res = resolve_requirement(req, self.manifest, substitution_rules=self.sub_rules)
        self.assertIsInstance(res, ResourceResolution)
        self.assertEqual(res.status, ResolutionStatus.EXACT)
        self.assertIsNotNone(res.selected)
        self.assertEqual(res.selected.id, "ambience_dark_01")
        self.assertGreaterEqual(res.score, 0.85)

    def test_substitute_intent_resolution(self):
        # "supernatural_reveal_riser" is not directly in manifest, but substitutes to "mystical_dark_riser"
        req = ResourceRequirement(
            id="REQ_02",
            type=ResourceCategory.SFX,
            intent="supernatural_reveal_riser",
            priority=RequirementPriority.RECOMMENDED,
            desired=DesiredProperties(intensity=3, duration_min=2.0, duration_max=4.0, tags=["dark", "mystical"]),
        )
        res = resolve_requirement(req, self.manifest, substitution_rules=self.sub_rules)
        self.assertIsInstance(res, ResourceResolution)
        self.assertEqual(res.status, ResolutionStatus.SUBSTITUTE)
        self.assertEqual(res.selected.id, "sfx_riser_mystical_01")
        self.assertTrue(res.recommendation["use_alternative"])
        self.assertGreaterEqual(res.score, 0.70)

    def test_missing_resolution_produces_gap(self):
        req = ResourceRequirement(
            id="REQ_03",
            type=ResourceCategory.SFX,
            intent="non_existent_unmatched_sound",
            priority=RequirementPriority.RECOMMENDED,
            beat_id="B04",
            narrative_context=NarrativeContext(role="climax", text="A thunderous shatter echoes across the cosmos."),
            desired=DesiredProperties(intensity=5, duration_min=3.0, duration_max=6.0, tags=["cosmic", "shatter"]),
        )
        gap = resolve_requirement(req, self.manifest, substitution_rules=self.sub_rules)
        self.assertIsInstance(gap, ResourceGap)
        self.assertEqual(gap.intent, "non_existent_unmatched_sound")
        self.assertEqual(gap.priority, RequirementPriority.RECOMMENDED)
        self.assertEqual(gap.used_at, ["B04"])
        self.assertIn("cosmic shatter sound effect", gap.suggested_search)

    def test_candidate_scoring_breakdown(self):
        req = ResourceRequirement(
            id="REQ_SCORE",
            type=ResourceCategory.SFX,
            intent="mystical_dark_riser",
            priority=RequirementPriority.RECOMMENDED,
            desired=DesiredProperties(intensity=3, duration_min=2.0, duration_max=4.0, tags=["dark", "mystical"]),
        )
        asset = self.manifest.find_by_id("sfx_riser_mystical_01")
        cand = score_candidate(req, asset, context=None, is_substitute=False)
        self.assertEqual(cand.breakdown.intent_score, 1.0)
        self.assertEqual(cand.breakdown.intensity_score, 1.0)
        self.assertEqual(cand.breakdown.duration_score, 1.0)
        self.assertEqual(cand.breakdown.tag_score, 1.0)
        self.assertGreater(cand.score, 0.90)

    def test_scoring_intensity_and_duration_penalties(self):
        req = ResourceRequirement(
            id="REQ_PENALTY",
            type=ResourceCategory.SFX,
            intent="mystical_dark_riser",
            desired=DesiredProperties(intensity=1, duration_min=10.0, duration_max=15.0), # asset is intensity 3, duration 3.5s
        )
        asset = self.manifest.find_by_id("sfx_riser_mystical_01")
        cand = score_candidate(req, asset, context=None, is_substitute=False)
        # Intensity diff = 2 -> score = 0.5
        self.assertEqual(cand.breakdown.intensity_score, 0.5)
        # Duration mismatch -> penalty
        self.assertLess(cand.breakdown.duration_score, 1.0)

    def test_anti_repeat_usage_penalty(self):
        req = ResourceRequirement(
            id="REQ_USAGE",
            type=ResourceCategory.SFX,
            intent="dark_supernatural_impact",
            desired=DesiredProperties(intensity=5),
        )
        asset = self.manifest.find_by_id("sfx_impact_supernatural_01") # total usage 5, used in proj_prev
        
        ctx_without_history = ResolutionContext(project_id="proj_curr")
        cand_no_hist = score_candidate(req, asset, context=ctx_without_history)

        ctx_with_history = ResolutionContext(project_id="proj_curr", recent_project_ids=["proj_prev", "proj_prev", "proj_prev"])
        cand_with_hist = score_candidate(req, asset, context=ctx_with_history)

        self.assertGreater(cand_no_hist.score, cand_with_hist.score)
        self.assertLess(cand_with_hist.breakdown.usage_score, cand_no_hist.breakdown.usage_score)

    def test_readiness_calculation_and_blocking_behavior(self):
        # Case 1: All required and recommended resolved -> Not blocked, high score
        plan_ok = VoicePlan(
            version=1,
            project=ProjectMetadata(id="proj_ok", title="Test OK", source_script="Hello."),
            voice=VoiceMetadata(profile="mythology_female_v1", provider="gemini", model="flash-tts"),
            global_direction=GlobalDirection(tone="mysterious", base_pace=0.92, dramatic_level=3, max_energy=5.0, avoid_overacting=True),
            beats=[
                Beat(
                    id="B01",
                    role=BeatRole.HOOK,
                    script=BeatScript(text="Hello ancient world."),
                    voice=VoiceDirection(emotion="suspense", energy=2.5, pause=PauseModel(before=0.1, after=0.7)),
                    ambience=AmbienceIntent(intent="ancient_dark_atmosphere", intensity="subtle", volume_db=-29.0),
                )
            ]
        )
        report_ok = resolve_project_resources(plan_ok, self.manifest, substitution_rules=self.sub_rules)
        self.assertFalse(report_ok.readiness.render_blocked)
        self.assertEqual(report_ok.readiness.score, 100)

        # Case 2: Recommended SFX missing -> Not blocked, but score < 100
        plan_rec_missing = VoicePlan(
            version=1,
            project=ProjectMetadata(id="proj_rec", title="Test Rec", source_script="Hello."),
            voice=VoiceMetadata(profile="mythology_female_v1", provider="gemini", model="flash-tts"),
            global_direction=GlobalDirection(tone="mysterious", base_pace=0.92, dramatic_level=3, max_energy=5.0, avoid_overacting=True),
            beats=[
                Beat(
                    id="B01",
                    role=BeatRole.SUPERNATURAL_EVENT,
                    script=BeatScript(text="A celestial beast roars."),
                    voice=VoiceDirection(emotion="dramatic", energy=4.0, pause=PauseModel(before=0.1, after=0.7)),
                    sfx=[
                        SFXIntent(
                            intent="missing_celestial_roar_sfx",
                            function=SFXFunction.EMPHASIS,
                            placement=SFXPlacement.PRE,
                            necessity=0.9,
                        )
                    ]
                )
            ]
        )
        report_rec = resolve_project_resources(plan_rec_missing, self.manifest, substitution_rules=self.sub_rules)
        self.assertFalse(report_rec.readiness.render_blocked)
        self.assertLess(report_rec.readiness.score, 100)
        self.assertEqual(len(report_rec.missing), 1)

    def test_suggested_search_generation(self):
        searches = generate_suggested_search(
            intent="supernatural_reveal_riser",
            tags=["dark", "mystical"],
            duration_min=2.0,
            duration_max=4.0,
            intensity=4,
        )
        self.assertTrue(any("supernatural reveal riser" in s for s in searches))
        self.assertTrue(any("riser sound effect" in s for s in searches))

    def test_malformed_yaml_raises_value_error(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tf:
            tf.write("invalid: yaml: [unbalanced")
            tf_path = tf.name

        try:
            with self.assertRaises(ValueError):
                load_manifest(tf_path)
            with self.assertRaises(ValueError):
                load_substitution_rules(tf_path)
            with self.assertRaises(ValueError):
                load_selection_rules(tf_path)
        finally:
            import os
            if os.path.exists(tf_path):
                os.unlink(tf_path)

    def test_load_selection_rules_no_global_default_mutation(self):
        import copy
        import tempfile
        from services.resource_manager import DEFAULT_SELECTION_RULES, DEFAULT_SUBSTITUTION_RULES

        original_selection = copy.deepcopy(DEFAULT_SELECTION_RULES)
        original_substitution = copy.deepcopy(DEFAULT_SUBSTITUTION_RULES)

        # Create custom YAML that modifies nested dictionary keys
        custom_yaml = (
            "version: 2\n"
            "scoring_weights:\n"
            "  intent: 0.99\n"
            "anti_repeat:\n"
            "  never_used_bonus: 0.88\n"
            "readiness_weights:\n"
            "  required: 99\n"
            "substitutions:\n"
            "  custom_intent:\n"
            "    - custom_alt_1\n"
        )

        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tf:
            tf.write(custom_yaml)
            tf_path = tf.name

        try:
            # 1. Load custom rules
            loaded_sel = load_selection_rules(tf_path)
            loaded_sub = load_substitution_rules(tf_path)

            self.assertEqual(loaded_sel["scoring_weights"]["intent"], 0.99)
            self.assertEqual(loaded_sel["anti_repeat"]["never_used_bonus"], 0.88)
            self.assertEqual(loaded_sel["readiness_weights"]["required"], 99)
            self.assertIn("custom_intent", loaded_sub)

            # 2. Assert global defaults were NOT mutated
            self.assertEqual(DEFAULT_SELECTION_RULES, original_selection)
            self.assertEqual(DEFAULT_SELECTION_RULES["scoring_weights"]["intent"], 0.40)
            self.assertEqual(DEFAULT_SELECTION_RULES["anti_repeat"]["never_used_bonus"], 0.10)
            self.assertEqual(DEFAULT_SELECTION_RULES["readiness_weights"]["required"], 5)
            self.assertEqual(DEFAULT_SUBSTITUTION_RULES, original_substitution)

            # 3. Call loader without override and assert pristine defaults are returned
            pristine_sel = load_selection_rules(path="/non/existent/path/rules.yaml")
            self.assertEqual(pristine_sel["scoring_weights"]["intent"], 0.40)
        finally:
            import os
            if os.path.exists(tf_path):
                os.unlink(tf_path)


if __name__ == "__main__":
    unittest.main()
