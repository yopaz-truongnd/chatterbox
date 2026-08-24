"""Unit tests for Phase 8 Per-Beat TTS Renderer and Provider Abstraction."""

from __future__ import annotations

import copy
from pathlib import Path
import shutil
import tempfile
import unittest
import yaml

from services.voice_plan import (
    Beat,
    BeatRole,
    BeatScript,
    GlobalDirection,
    PauseModel,
    ProjectMetadata,
    VoiceDirection,
    VoiceMetadata,
    VoicePlan,
)
from services.resource_models import (
    ReadinessReport,
    RequirementPriority,
    ResourceCategory,
    ResourceGap,
    ResourceReport,
)
from services.render_models import (
    RenderManifest,
    RenderStatus,
    TTSRenderRequest,
)
from services.tts.fake import FakeTTSProvider
from services.tts.gemini import GeminiTTSProvider, map_voice_plan_to_gemini_payload
from services.voice_renderer import (
    ProviderUnavailableError,
    ResourceBlockedError,
    load_render_manifest,
    render_project_narration,
    render_single_beat_attempt,
)


class TestVoiceRendererPhase8(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="voice_render_test_"))
        self.provider = FakeTTSProvider(sample_rate=24000)

        self.plan = VoicePlan(
            version=1,
            project=ProjectMetadata(id="proj_torch", title="Torch Dragon", source_script="When Zhulong opened its eyes."),
            voice=VoiceMetadata(profile="mythology_male_v1", provider="fake", model="fake-tts"),
            global_direction=GlobalDirection(tone="mysterious", base_pace=0.92, dramatic_level=3, max_energy=5.0, avoid_overacting=True),
            beats=[
                Beat(
                    id="B01",
                    role=BeatRole.HOOK,
                    script=BeatScript(text="Beyond the northern extremes lies Mount Zhong."),
                    voice=VoiceDirection(emotion="suspense", energy=2.5, pace=0.95, pause=PauseModel(before=0.1, after=0.7)),
                ),
                Beat(
                    id="B02",
                    role=BeatRole.SUPERNATURAL_EVENT,
                    script=BeatScript(text="When Zhulong opened its eyes, eternal daylight illuminated the darkness."),
                    voice=VoiceDirection(emotion="dramatic", energy=4.0, pace=1.0, pause=PauseModel(before=0.2, after=0.8)),
                ),
            ],
        )

        # Setup project directory structure
        (self.temp_dir / "source").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "renders").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "qc").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "logs").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_one_beat_one_provider_call_and_script_preservation(self):
        plan_copy = copy.deepcopy(self.plan)

        # Render single beat B01
        attempt = render_single_beat_attempt(
            project_dir=self.temp_dir,
            project_id="proj_torch",
            beat=self.plan.beats[0],
            provider=self.provider,
            attempt_id=1,
            pronunciation_overrides={"Zhulong": "Joo-long"},
        )

        self.assertEqual(attempt.status, RenderStatus.RENDERED)
        self.assertEqual(attempt.attempt, 1)
        self.assertTrue(Path(attempt.audio_path).exists())
        self.assertEqual(self.provider.render_call_count, 1)

        # Invariant: text in request must match Beat.script.text exactly
        last_req = self.provider.rendered_requests[-1]
        self.assertEqual(last_req.text, self.plan.beats[0].script.text)
        self.assertEqual(last_req.pronunciation["Zhulong"], "Joo-long")

        # Invariant: input VoicePlan is unchanged
        self.assertEqual(self.plan, plan_copy)

    def test_render_blocked_if_resource_report_blocked(self):
        blocked_report = ResourceReport(
            project_id="proj_torch",
            readiness=ReadinessReport(
                score=40,
                render_blocked=True,
                required_missing_count=1,
                recommended_missing_count=1,
                block_reasons=["Missing required proper noun: Qiongqi"],
            ),
            resolved=[],
            substituted=[],
            missing=[
                ResourceGap(
                    id="gap_qiongqi",
                    type=ResourceCategory.KNOWLEDGE,
                    term="Qiongqi",
                    priority=RequirementPriority.REQUIRED,
                )
            ],
            pronunciation_overrides={},
        )

        # Attempt to render should raise ResourceBlockedError
        with self.assertRaises(ResourceBlockedError):
            render_project_narration(
                project_dir=self.temp_dir,
                plan=self.plan,
                provider=self.provider,
                resource_report=blocked_report,
                force=False,
            )

    def test_idempotency_and_resume_skips_passed_beats(self):
        # 1. First run: render both beats
        manifest, _ = render_project_narration(
            project_dir=self.temp_dir,
            plan=self.plan,
            provider=self.provider,
            auto_qc=True,
        )

        self.assertEqual(len(manifest.beats), 2)
        self.assertEqual(self.provider.render_call_count, 2)

        # 2. Second run without force: should skip all passed beats
        manifest_2, _ = render_project_narration(
            project_dir=self.temp_dir,
            plan=self.plan,
            provider=self.provider,
            auto_qc=True,
            force=False,
        )

        # Render count should still be 2 (no new calls made)
        self.assertEqual(self.provider.render_call_count, 2)

    def test_selective_rerender_increments_attempt(self):
        # 1. Initial render
        render_project_narration(
            project_dir=self.temp_dir,
            plan=self.plan,
            provider=self.provider,
            auto_qc=True,
        )

        # 2. Selective rerender of B02
        manifest, _ = render_project_narration(
            project_dir=self.temp_dir,
            plan=self.plan,
            provider=self.provider,
            beats_filter=["B02"],
            auto_qc=True,
            force=True,
        )

        b02_state = manifest.beats["B02"]
        self.assertEqual(len(b02_state.attempts), 2)
        self.assertEqual(b02_state.selected_attempt, 2)

        # B01 was NOT rerendered
        b01_state = manifest.beats["B01"]
        self.assertEqual(len(b01_state.attempts), 1)

    def test_gemini_direction_payload_mapping(self):
        req = TTSRenderRequest(
            project_id="proj_g",
            beat_id="B01",
            text="When Zhulong opened its eyes.",
            voice_profile="mythology_narrator_male",
            emotion="dramatic",
            energy=4.2,
            pace=0.92,
            target_wpm=130,
            director_note="Keep intense vocal posture",
            pronunciation={"Zhulong": "Joo-long"},
            emphasis=["Zhulong", "eyes"],
        )

        payload = map_voice_plan_to_gemini_payload(req)

        self.assertEqual(payload["text"], "When Zhulong opened its eyes.")
        self.assertEqual(payload["voice_profile"], "mythology_narrator_male")
        self.assertIn("Emotion/Tone: dramatic", payload["system_instruction"])
        self.assertIn("Energy Level (1-5): 4.2", payload["system_instruction"])
        self.assertIn("Pace Multiplier: 0.92", payload["system_instruction"])
        self.assertIn("Target Pacing: 130 WPM", payload["system_instruction"])
        self.assertIn("Zhulong", payload["system_instruction"])


if __name__ == "__main__":
    unittest.main()
