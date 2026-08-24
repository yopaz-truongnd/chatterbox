"""Unit tests for Phase 5 Pronunciation Knowledge service."""

import unittest
from services.voice_plan import (
    VoicePlan,
    Beat,
    BeatRole,
    BeatScript,
    VoiceDirection,
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
    ResourceManifest,
)
from services.pronunciation_knowledge import (
    load_pronunciation_knowledge,
    normalize_term,
    lookup_term,
    check_term_status,
    evaluate_script_pronunciation,
)
from services.resource_manager import resolve_project_resources


class TestPronunciationKnowledgePhase5(unittest.TestCase):

    def setUp(self):
        self.knowledge = PronunciationKnowledge(
            version=1,
            terms={
                "zhulong": PronunciationEntry(
                    display="Zhulong",
                    aliases=["Zhu Long", "Torch Dragon"],
                    language="zh",
                    pronunciation=PronunciationHint(tts_hint="Joo-long", ipa="ʈʂu˥ luŋ˧˥"),
                    status=PronunciationStatus.VERIFIED,
                    source="manual",
                ),
                "taotie": PronunciationEntry(
                    display="Taotie",
                    aliases=["Tao Tie"],
                    language="zh",
                    pronunciation=PronunciationHint(tts_hint="Tow-tyeh", ipa="tʰɑʊ˥ tʰjɛ˥˩"),
                    status=PronunciationStatus.VERIFIED,
                    source="manual",
                ),
                "qiongqi": PronunciationEntry(
                    display="Qiongqi",
                    aliases=["Qiong Qi"],
                    language="zh",
                    pronunciation=PronunciationHint(tts_hint=None, ipa=None),
                    status=PronunciationStatus.UNVERIFIED,
                    source="manual",
                ),
                "taowu": PronunciationEntry(
                    display="Taowu",
                    aliases=["Tao Wu"],
                    language="zh",
                    pronunciation=PronunciationHint(tts_hint="Wrong", ipa=None),
                    status=PronunciationStatus.REJECTED,
                    source="manual",
                ),
            },
        )

    def test_normalize_term(self):
        self.assertEqual(normalize_term("Zhulong"), "zhulong")
        self.assertEqual(normalize_term("  ZHU-LONG  "), "zhu long")
        self.assertEqual(normalize_term('"Torch Dragon!"'), "torch dragon")
        self.assertEqual(normalize_term(""), "")

    def test_verified_lookup(self):
        key, entry = lookup_term("Zhulong", self.knowledge)
        self.assertEqual(key, "zhulong")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.status, PronunciationStatus.VERIFIED)
        self.assertEqual(entry.pronunciation.tts_hint, "Joo-long")

    def test_alias_lookup(self):
        # Alias 1: "Torch Dragon"
        key, entry = lookup_term("Torch Dragon", self.knowledge)
        self.assertEqual(key, "zhulong")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.display, "Zhulong")

        # Alias 2: "Zhu Long"
        key, entry = lookup_term("Zhu Long", self.knowledge)
        self.assertEqual(key, "zhulong")

    def test_case_insensitive_and_normalized_lookup(self):
        key1, entry1 = lookup_term("zhulong", self.knowledge)
        key2, entry2 = lookup_term("  ZHULONG! ", self.knowledge)
        key3, entry3 = lookup_term("zhu-long", self.knowledge)
        self.assertEqual(key1, "zhulong")
        self.assertEqual(key2, "zhulong")
        self.assertEqual(key3, "zhulong")

    def test_unverified_and_rejected_status(self):
        status_q, entry_q = check_term_status("Qiongqi", self.knowledge)
        self.assertEqual(status_q, PronunciationStatus.UNVERIFIED)

        status_tw, entry_tw = check_term_status("Taowu", self.knowledge)
        self.assertEqual(status_tw, PronunciationStatus.REJECTED)

        status_unknown, entry_unknown = check_term_status("UnknownDeity", self.knowledge)
        self.assertEqual(status_unknown, PronunciationStatus.UNVERIFIED)
        self.assertIsNone(entry_unknown)

    def test_evaluate_script_pronunciation_no_script_mutation(self):
        script_text = "Long ago, Zhulong rested upon the cosmic mountain while Qiongqi roamed the dark valleys."
        original_copy = str(script_text)

        result = evaluate_script_pronunciation(script_text, self.knowledge)

        # Assert script_text is unchanged
        self.assertEqual(script_text, original_copy)

        # Zhulong is verified -> override present
        self.assertIn("Zhulong", result["verified_overrides"])
        self.assertEqual(result["verified_overrides"]["Zhulong"], "Joo-long")

        # Qiongqi is unverified -> gap present
        gaps = result["knowledge_gaps"]
        qiongqi_gap = next((g for g in gaps if g.term == "Qiongqi"), None)
        self.assertIsNotNone(qiongqi_gap)
        self.assertEqual(qiongqi_gap.type, ResourceCategory.KNOWLEDGE)
        self.assertEqual(qiongqi_gap.priority, RequirementPriority.REQUIRED)

    def test_voice_plan_pronunciation_integration(self):
        manifest = ResourceManifest(version=1, resources=[])
        plan = VoicePlan(
            version=1,
            project=ProjectMetadata(id="proj_p5", title="Myth Test", source_script="When Zhulong opened its eyes."),
            voice=VoiceMetadata(profile="mythology_female_v1", provider="gemini", model="flash-tts"),
            global_direction=GlobalDirection(tone="mysterious", base_pace=0.92, dramatic_level=3, max_energy=5.0, avoid_overacting=True),
            beats=[
                Beat(
                    id="B01",
                    role=BeatRole.REVEAL,
                    script=BeatScript(text="When Zhulong opened its eyes, the cosmos awakened."),
                    voice=VoiceDirection(emotion="dramatic", energy=3.0, pause=PauseModel(before=0.1, after=0.7)),
                )
            ]
        )

        # Zhulong is verified in self.knowledge
        report = resolve_project_resources(plan, manifest, knowledge=self.knowledge)
        self.assertFalse(report.readiness.render_blocked)
        
        # 1. Assert input plan was NOT mutated (read-only resolution contract)
        self.assertEqual(plan.beats[0].voice.pronunciation, {})

        # 2. Assert overrides are populated in ResourceReport
        self.assertIn("Zhulong", report.pronunciation_overrides)
        self.assertEqual(report.pronunciation_overrides["Zhulong"], "Joo-long")

        # 3. Assert verified knowledge is present in resolved list
        resolved_know = next((r for r in report.resolved if r.type == ResourceCategory.KNOWLEDGE), None)
        self.assertIsNotNone(resolved_know)
        self.assertEqual(resolved_know.requested_intent, "Zhulong")
        self.assertEqual(resolved_know.status, ResolutionStatus.EXACT)

    def test_unverified_pronunciation_blocks_render(self):
        manifest = ResourceManifest(version=1, resources=[])
        plan = VoicePlan(
            version=1,
            project=ProjectMetadata(id="proj_block", title="Block Test", source_script="The fearsome Qiongqi struck fear into all mortals."),
            voice=VoiceMetadata(profile="mythology_female_v1", provider="gemini", model="flash-tts"),
            global_direction=GlobalDirection(tone="mysterious", base_pace=0.92, dramatic_level=3, max_energy=5.0, avoid_overacting=True),
            beats=[
                Beat(
                    id="B01",
                    role=BeatRole.HOOK,
                    script=BeatScript(text="The fearsome Qiongqi struck fear into all mortals."),
                    voice=VoiceDirection(emotion="suspense", energy=3.0, pause=PauseModel(before=0.1, after=0.7)),
                )
            ]
        )

        report = resolve_project_resources(plan, manifest, knowledge=self.knowledge)
        # Qiongqi is unverified -> render must be BLOCKED
        self.assertTrue(report.readiness.render_blocked)
        self.assertEqual(report.readiness.required_missing_count, 1)
        self.assertTrue(any("Qiongqi" in reason for reason in report.readiness.block_reasons))

    def test_malformed_pronunciation_yaml_raises_value_error(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tf:
            tf.write("terms:\n  bad_yaml: [unterminated")
            tf_path = tf.name

        try:
            with self.assertRaises(ValueError):
                load_pronunciation_knowledge(tf_path)
        finally:
            import os
            if os.path.exists(tf_path):
                os.unlink(tf_path)


if __name__ == "__main__":
    unittest.main()
