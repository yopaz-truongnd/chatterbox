"""Unit tests for Phase 9 Voice Quality Control (QC)."""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from services.voice_plan import (
    Beat,
    BeatRole,
    BeatScript,
    PauseModel,
    VoiceDirection,
)
from services.render_models import (
    BeatQCResult,
    QCVerdict,
    RenderAttempt,
    RenderStatus,
)
from services.tts.fake import FakeTTSProvider
from services.voice_qc import (
    evaluate_beat_qc,
    evaluate_content_qc,
    evaluate_direction_qc,
    evaluate_signal_qc,
    select_best_candidate,
)


class TestVoiceQCPhase9(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="voice_qc_test_"))
        self.beat = Beat(
            id="B01",
            role=BeatRole.REVEAL,
            script=BeatScript(text="When Zhulong opened its eyes, eternal daylight appeared."),
            voice=VoiceDirection(
                emotion="dramatic",
                energy=4.0,
                pace=1.0,
                target_wpm=138,
                pause=PauseModel(before=0.1, after=0.8),
            ),
        )

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_signal_qc_detects_clean_audio(self):
        provider = FakeTTSProvider(sample_rate=24000)
        from services.render_models import TTSRenderRequest

        req = TTSRenderRequest(
            project_id="p1",
            beat_id="B01",
            text="Clean test speech audio.",
        )
        res = provider.render(req, self.temp_dir)

        sig_res = evaluate_signal_qc(res.audio_path)
        self.assertTrue(sig_res.passed)
        self.assertFalse(sig_res.clipping_detected)
        self.assertGreater(sig_res.duration, 0.5)

    def test_signal_qc_detects_clipping(self):
        provider = FakeTTSProvider(
            sample_rate=24000,
            simulate_clipping_beats=["B01"],
        )
        from services.render_models import TTSRenderRequest

        req = TTSRenderRequest(
            project_id="p1",
            beat_id="B01",
            text="Clipping test audio.",
        )
        res = provider.render(req, self.temp_dir)

        sig_res = evaluate_signal_qc(res.audio_path)
        self.assertFalse(sig_res.passed)
        self.assertTrue(sig_res.clipping_detected)
        self.assertTrue(any("clipping" in i.lower() for i in sig_res.issues))

    def test_signal_qc_detects_silence(self):
        provider = FakeTTSProvider(
            sample_rate=24000,
            simulate_silent_beats=["B01"],
        )
        from services.render_models import TTSRenderRequest

        req = TTSRenderRequest(
            project_id="p1",
            beat_id="B01",
            text="Silent test audio.",
        )
        res = provider.render(req, self.temp_dir)

        sig_res = evaluate_signal_qc(res.audio_path)
        self.assertFalse(sig_res.passed)
        self.assertTrue(any("silent" in i.lower() for i in sig_res.issues))

    def test_direction_qc_duration_evaluation(self):
        # 8 words at 138 WPM -> expected duration ~ 3.48s
        # If actual duration is 3.5s -> within tolerance -> pass
        dir_res = evaluate_direction_qc(
            beat=self.beat,
            actual_duration=3.5,
            actual_wpm=138.0,
        )
        self.assertTrue(dir_res.passed)

        # If actual duration is 0.2s -> too fast -> warning
        dir_res_fast = evaluate_direction_qc(
            beat=self.beat,
            actual_duration=0.2,
            actual_wpm=300.0,
        )
        self.assertTrue(any("fast" in w for w in dir_res_fast.warnings))

    def test_beat_qc_verdict_pass_on_clean_render(self):
        provider = FakeTTSProvider(sample_rate=24000)
        from services.render_models import TTSRenderRequest

        req = TTSRenderRequest(
            project_id="p1",
            beat_id="B01",
            text=self.beat.script.text,
        )
        res = provider.render(req, self.temp_dir)

        qc = evaluate_beat_qc(
            beat=self.beat,
            audio_path=res.audio_path,
            attempt_id=1,
            pronunciation_overrides={"Zhulong": "Joo-long"},
        )

        self.assertEqual(qc.verdict, QCVerdict.PASS)
        self.assertGreaterEqual(qc.qc_score, 85.0)

    def test_retry_policy_on_failure_and_deterministic_adjustment(self):
        provider = FakeTTSProvider(
            sample_rate=24000,
            simulate_clipping_beats=["B01"],
        )
        from services.render_models import TTSRenderRequest

        req = TTSRenderRequest(
            project_id="p1",
            beat_id="B01",
            text=self.beat.script.text,
        )
        res = provider.render(req, self.temp_dir)

        # Attempt 1 failed -> verdict should be RETRY
        qc_att1 = evaluate_beat_qc(
            beat=self.beat,
            audio_path=res.audio_path,
            attempt_id=1,
            max_retries=3,
        )
        self.assertEqual(qc_att1.verdict, QCVerdict.RETRY)
        self.assertIsNotNone(qc_att1.retry_adjustment)

        # Attempt 3 failed -> verdict should be FAIL or NEEDS_REVIEW (max retries reached)
        qc_att3 = evaluate_beat_qc(
            beat=self.beat,
            audio_path=res.audio_path,
            attempt_id=3,
            max_retries=3,
        )
        self.assertIn(qc_att3.verdict, [QCVerdict.FAIL, QCVerdict.NEEDS_REVIEW])

    def test_candidate_selection_ranking(self):
        att1 = RenderAttempt(
            attempt=1,
            provider="fake",
            model="fake-tts",
            status=RenderStatus.PASSED,
            audio_path="a1.wav",
            duration=3.5,
            qc_result=BeatQCResult(
                beat_id="B01",
                attempt_id=1,
                signal=evaluate_signal_qc(Path("nonexistent")),
                content=evaluate_content_qc(Path("nonexistent"), "text"),
                direction=evaluate_direction_qc(self.beat, 3.5, 138),
                verdict=QCVerdict.PASS,
                qc_score=85.0,
            ),
        )

        att2 = RenderAttempt(
            attempt=2,
            provider="fake",
            model="fake-tts",
            status=RenderStatus.PASSED,
            audio_path="a2.wav",
            duration=3.4,
            qc_result=BeatQCResult(
                beat_id="B01",
                attempt_id=2,
                signal=evaluate_signal_qc(Path("nonexistent")),
                content=evaluate_content_qc(Path("nonexistent"), "text"),
                direction=evaluate_direction_qc(self.beat, 3.4, 138),
                verdict=QCVerdict.PASS,
                qc_score=95.0,
            ),
        )

        # Candidate selection should select att2 because qc_score 95 > 85
        best = select_best_candidate([att1, att2])
        self.assertEqual(best.attempt, 2)


if __name__ == "__main__":
    unittest.main()
