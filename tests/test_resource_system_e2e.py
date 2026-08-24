"""End-to-End Integration Tests for Phase 4-6 Resource System."""

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
    PronunciationEntry,
    PronunciationHint,
    PronunciationKnowledge,
    PronunciationStatus,
    RequirementPriority,
    ResolutionStatus,
    ResourceCategory,
    ResourceEntry,
    ResourceFile,
    ResourceManifest,
    ResourceMixSettings,
    ResourceProperties,
    ResourceUsage,
)
from services.resource_manager import (
    load_manifest,
    load_substitution_rules,
    load_selection_rules,
    resolve_project_resources,
)
from services.pronunciation_knowledge import load_pronunciation_knowledge


class TestResourceSystemE2E(unittest.TestCase):

    def setUp(self):
        # 1. Manifest Fixture
        self.manifest = ResourceManifest(
            version=1,
            resources=[
                # Exact Ambience
                ResourceEntry(
                    id="ambience_dark_001",
                    file=ResourceFile(path="ambience/dark/dark_wind_01.wav", format="wav"),
                    category=ResourceCategory.AMBIENCE,
                    intents=["ancient_dark_atmosphere"],
                    tags=["dark", "ancient", "wind", "mysterious"],
                    properties=ResourceProperties(duration=43.2, loopable=True, intensity=2),
                    mix=ResourceMixSettings(recommended_db=-29.0, max_db=-24.0),
                    usage=ResourceUsage(total=0, last_used=None, recent_projects=[]),
                ),
                # Substitute SFX target (mystical_dark_riser matches substitution for supernatural_reveal_riser)
                ResourceEntry(
                    id="sfx_riser_mystical_001",
                    file=ResourceFile(path="sfx/riser/mystical_dark_riser_01.wav", format="wav"),
                    category=ResourceCategory.SFX,
                    intents=["mystical_dark_riser"],
                    tags=["dark", "mystical", "riser"],
                    properties=ResourceProperties(duration=3.5, loopable=False, intensity=3),
                    mix=ResourceMixSettings(recommended_db=-22.0, max_db=-18.0),
                    usage=ResourceUsage(total=0, last_used=None, recent_projects=[]),
                ),
            ],
        )

        # 2. Substitution Rules
        self.sub_rules = {
            "supernatural_reveal_riser": [
                "mystical_dark_riser",
            ]
        }

        # 3. Knowledge Base Fixture (Zhulong verified, Qiongqi unverified)
        self.knowledge = PronunciationKnowledge(
            version=1,
            terms={
                "zhulong": PronunciationEntry(
                    display="Zhulong",
                    aliases=["Zhu Long", "Torch Dragon"],
                    language="zh",
                    pronunciation=PronunciationHint(tts_hint="Joo-long"),
                    status=PronunciationStatus.VERIFIED,
                ),
                "qiongqi": PronunciationEntry(
                    display="Qiongqi",
                    aliases=["Qiong Qi"],
                    language="zh",
                    pronunciation=PronunciationHint(tts_hint=None),
                    status=PronunciationStatus.UNVERIFIED,
                ),
            },
        )

    def test_full_resource_pipeline_acceptance_scenario(self):
        """Test full pipeline:
        
        - 1 exact ambience (ancient_dark_atmosphere)
        - 1 substituted SFX (supernatural_reveal_riser -> mystical_dark_riser)
        - 1 missing recommended SFX (mythological_creature_roar)
        - 1 verified pronunciation (Zhulong)
        - 1 missing required pronunciation (Qiongqi)
        
        Expected: render_blocked = True solely because Qiongqi is missing/unverified.
        """
        source_script = (
            "Beyond the northern seas, the great deity Zhulong slumbered upon the crimson mountain peaks.\n"
            "When Zhulong opened its eyes, daylight suddenly appeared.\n"
            "In the deep shadows, the winged beast Qiongqi emerged and let out a dreadful roar."
        )

        directed_voice_plan = VoicePlan(
            version=1,
            project=ProjectMetadata(
                id="proj_mythology_001",
                title="The Torch Dragon and the Four Fiends",
                source_script=source_script,
            ),
            voice=VoiceMetadata(
                profile="mythology_narrator_male",
                provider="gemini",
                model="gemini-3.1-flash-tts-preview",
            ),
            global_direction=GlobalDirection(
                tone="ancient_cinematic",
                base_pace=0.90,
                dramatic_level=4,
                max_energy=5.0,
                avoid_overacting=True,
            ),
            beats=[
                # Beat 1: Exact Ambience + Zhulong (verified)
                Beat(
                    id="B01",
                    role=BeatRole.HOOK,
                    script=BeatScript(text="Beyond the northern seas, the great deity Zhulong slumbered upon the crimson mountain peaks."),
                    voice=VoiceDirection(
                        emotion="suspense",
                        energy=2.5,
                        pause=PauseModel(before=0.1, after=0.8),
                    ),
                    ambience=AmbienceIntent(
                        intent="ancient_dark_atmosphere",
                        intensity="subtle",
                        volume_db=-29.0,
                    ),
                    sfx=[],
                ),
                # Beat 2: Substituted SFX (supernatural_reveal_riser -> mystical_dark_riser)
                Beat(
                    id="B02",
                    role=BeatRole.SUPERNATURAL_EVENT,
                    script=BeatScript(text="When Zhulong opened its eyes, daylight suddenly appeared."),
                    voice=VoiceDirection(
                        emotion="dramatic",
                        energy=4.2,
                        pause=PauseModel(before=0.2, after=0.7),
                    ),
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
                ),
                # Beat 3: Missing SFX (mythological_creature_roar) + Qiongqi (unverified)
                Beat(
                    id="B03",
                    role=BeatRole.CLIMAX,
                    script=BeatScript(text="In the deep shadows, the winged beast Qiongqi emerged and let out a dreadful roar."),
                    voice=VoiceDirection(
                        emotion="dramatic",
                        energy=4.8,
                        pause=PauseModel(before=0.2, after=1.0),
                    ),
                    ambience=None,
                    sfx=[
                        SFXIntent(
                            intent="mythological_creature_roar",
                            function=SFXFunction.EMPHASIS,
                            placement=SFXPlacement.UNDER,
                            intensity="prominent",
                            necessity=0.80,
                        )
                    ],
                ),
            ],
        )

        # Execute Resource Resolution
        report = resolve_project_resources(
            plan=directed_voice_plan,
            manifest=self.manifest,
            knowledge=self.knowledge,
            substitution_rules=self.sub_rules,
        )

        # 1. Check Exact Match
        exact_ambience = next((r for r in report.resolved if r.type == ResourceCategory.AMBIENCE), None)
        self.assertIsNotNone(exact_ambience)
        self.assertEqual(exact_ambience.status, ResolutionStatus.EXACT)
        self.assertEqual(exact_ambience.selected.id, "ambience_dark_001")

        # 2. Check Substituted Match
        substituted_sfx = next((r for r in report.substituted if r.type == ResourceCategory.SFX), None)
        self.assertIsNotNone(substituted_sfx)
        self.assertEqual(substituted_sfx.status, ResolutionStatus.SUBSTITUTE)
        self.assertEqual(substituted_sfx.requested_intent, "supernatural_reveal_riser")
        self.assertEqual(substituted_sfx.selected.id, "sfx_riser_mystical_001")
        self.assertTrue(substituted_sfx.recommendation["use_alternative"])

        # 3. Check Missing SFX (RECOMMENDED priority, does not block on its own)
        missing_sfx = next((g for g in report.missing if g.type == ResourceCategory.SFX), None)
        self.assertIsNotNone(missing_sfx)
        self.assertEqual(missing_sfx.intent, "mythological_creature_roar")
        self.assertEqual(missing_sfx.priority, RequirementPriority.RECOMMENDED)

        # 4. Check Missing Pronunciation Gap (REQUIRED priority)
        missing_pron = next((g for g in report.missing if g.type == ResourceCategory.KNOWLEDGE), None)
        self.assertIsNotNone(missing_pron)
        self.assertEqual(missing_pron.term, "Qiongqi")
        self.assertEqual(missing_pron.priority, RequirementPriority.REQUIRED)

        # 5. Check Render Blocked Status and Structured Readiness Score
        # Blocked strictly because of REQUIRED pronunciation gap Qiongqi
        self.assertTrue(report.readiness.render_blocked)
        self.assertEqual(report.readiness.required_missing_count, 1)
        self.assertTrue(any("Qiongqi" in b for b in report.readiness.block_reasons))
        # Ambience (2 earned / 2 total) + SFX sub (2 earned / 2 total) + SFX missing (0 earned / 2 total) + Zhulong (5 earned / 5 total) + Qiongqi (0 earned / 5 total) = 9/16 = 56%
        self.assertEqual(report.readiness.score, 56)

        # 6. Check that input VoicePlan was NOT mutated (read-only contract)
        self.assertEqual(directed_voice_plan.beats[0].voice.pronunciation, {})
        self.assertIn("Zhulong", directed_voice_plan.beats[0].script.text)
        self.assertNotIn("Joo-long", directed_voice_plan.beats[0].script.text)

        # 7. Check Verified Pronunciation Overrides in Report
        self.assertEqual(report.pronunciation_overrides.get("Zhulong"), "Joo-long")

        # 8. Check Resolved list contains both Exact Ambience and Verified Pronunciation
        resolved_know = next((r for r in report.resolved if r.type == ResourceCategory.KNOWLEDGE), None)
        self.assertIsNotNone(resolved_know)
        self.assertEqual(resolved_know.requested_intent, "Zhulong")

    def test_default_repo_configs_load_cleanly(self):
        """Verify that default config files in repo (manifest.yaml, pronunciation.yaml, rules) load properly."""
        manifest = load_manifest()
        self.assertGreater(len(manifest.resources), 0)

        knowledge = load_pronunciation_knowledge()
        self.assertGreater(len(knowledge.terms), 0)
        self.assertIn("zhulong", knowledge.terms)

        sub_rules = load_substitution_rules()
        self.assertGreater(len(sub_rules), 0)

        sel_rules = load_selection_rules()
        self.assertIn("scoring_weights", sel_rules)


if __name__ == "__main__":
    unittest.main()
