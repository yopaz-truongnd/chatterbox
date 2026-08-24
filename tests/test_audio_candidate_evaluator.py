"""Unit and regression tests for canonical AudioCandidateEvaluator (Phase 10B)."""

from __future__ import annotations

import io
import math
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
import unittest.mock as mock
import wave
import torch

from services.audio_candidate_evaluator import (
    AudioCandidateEvaluator,
    CandidateEvaluation,
    evaluate_direction_layer,
    rank_candidates,
)
from services.voice_qc import evaluate_beat_qc
from services.voice_plan import Beat, BeatRole, BeatScript, VoiceDirection


class TestAudioCandidateEvaluatorPhase10B(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="cand_eval_test_"))
        
        # Build 1.0s clean sine wave tensor
        samples = []
        for i in range(24000):
            val = 0.4 * math.sin(2.0 * math.pi * 440.0 * (i / 24000.0))
            samples.append(val)
        self.clean_tensor = torch.tensor(samples, dtype=torch.float32).unsqueeze(0)

        # Write clean WAV to disk
        self.clean_wav_path = self.temp_dir / "clean.wav"
        with wave.open(str(self.clean_wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            int_samples = [int(s * 32767) for s in samples]
            wf.writeframes(struct.pack(f"<{len(int_samples)}h", *int_samples))

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_default_vs_voice_director_scoring_profiles(self):
        evaluator_default = AudioCandidateEvaluator(profile="default")
        evaluator_voice = AudioCandidateEvaluator(profile="voice_director")

        self.assertEqual(evaluator_default.weights["content"], 0.60)
        self.assertEqual(evaluator_default.weights["signal"], 0.40)
        self.assertEqual(evaluator_default.weights["direction"], 0.00)

        self.assertEqual(evaluator_voice.weights["content"], 0.50)
        self.assertEqual(evaluator_voice.weights["signal"], 0.30)
        self.assertEqual(evaluator_voice.weights["direction"], 0.20)

    def test_evaluate_clean_audio_passes(self):
        evaluator = AudioCandidateEvaluator(profile="voice_director")
        res = evaluator.evaluate(
            audio_source=self.clean_wav_path,
            reference_text="A clean test sentence.",
            direction={"target_wpm": 138, "pace": 1.0},
        )

        self.assertTrue(res.passed)
        self.assertGreaterEqual(res.score, 75.0)
        self.assertFalse(res.retry_recommended)
        self.assertIsNotNone(res.direction)

    def test_direction_layer_optional_when_direction_absent(self):
        evaluator = AudioCandidateEvaluator(profile="default")
        res = evaluator.evaluate(
            audio_source=self.clean_tensor,
            reference_text="Testing default profile without direction.",
            direction=None,
        )

        self.assertTrue(res.passed)
        self.assertIsNone(res.direction)
        self.assertEqual(res.profile, "default")

    def test_auto_fix_signal_integration(self):
        # Create hot/clipping tensor (amplified above 1.0)
        hot_samples = [1.8 * math.sin(2.0 * math.pi * 440.0 * (i / 24000.0)) for i in range(24000)]
        hot_tensor = torch.tensor(hot_samples, dtype=torch.float32).unsqueeze(0)

        evaluator = AudioCandidateEvaluator(profile="default", auto_fix_signal=True)
        res = evaluator.evaluate(
            audio_source=hot_tensor,
            reference_text="Audio that gets auto fixed.",
        )

        self.assertTrue(res.passed)
        self.assertTrue(len(res.actions_taken) > 0)

    def test_retry_policy_on_missing_words(self):
        evaluator = AudioCandidateEvaluator(profile="voice_director")
        
        # Mock evaluate_speech_content to simulate missing words
        mock_content = {
            "passed": False,
            "score": 60.0,
            "missing_words": ["zhulong", "eyes"],
            "repeated_words": [],
            "accuracy_percent": 65.0,
            "transcription": "A dragon was here.",
            "actual_wpm": 130,
            "issues": ["Missing words: zhulong, eyes"],
            "warnings": [],
        }

        with mock.patch("services.audio_candidate_evaluator.evaluate_speech_content", return_value=mock_content):
            res = evaluator.evaluate(
                audio_source=self.clean_tensor,
                reference_text="Zhulong opened its eyes.",
                direction={"target_wpm": 130},
            )

            self.assertFalse(res.passed)
            self.assertTrue(res.retry_recommended)
            self.assertIn("Content omission", res.retry_reason)
            self.assertIn("director_note", res.retry_adjustment)

    def test_candidate_ranking_and_deterministic_tie_breaking(self):
        # Candidate 1: Passed, score 95
        c1 = CandidateEvaluation(
            passed=True,
            score=95.0,
            content={"accuracy_percent": 98.0},
            direction={"duration_deviation": 0.05},
        )
        # Candidate 2: Passed, score 90
        c2 = CandidateEvaluation(
            passed=True,
            score=90.0,
            content={"accuracy_percent": 92.0},
            direction={"duration_deviation": 0.08},
        )
        # Candidate 3: Failed, score 50
        c3 = CandidateEvaluation(
            passed=False,
            score=50.0,
            content={"accuracy_percent": 60.0},
            direction={"duration_deviation": 0.30},
        )

        ranked = rank_candidates([c3, c2, c1])
        self.assertEqual(ranked[0], c1)
        self.assertEqual(ranked[1], c2)
        self.assertEqual(ranked[2], c3)

    def test_same_candidate_in_both_pipelines_parity(self):
        evaluator_batch = AudioCandidateEvaluator(profile="default", auto_fix_signal=False)
        evaluator_voice = AudioCandidateEvaluator(profile="voice_director", auto_fix_signal=False)

        ref_text = "The ancient dragon of Mount Zhong."

        res_batch = evaluator_batch.evaluate(self.clean_wav_path, ref_text)
        res_voice = evaluator_voice.evaluate(self.clean_wav_path, ref_text, direction={"target_wpm": 138})

        # Signal and content raw metrics should be identical
        self.assertEqual(res_batch.signal["rms_db"], res_voice.signal["rms_db"])
        self.assertEqual(res_batch.signal["peak"], res_voice.signal["peak"])
        self.assertEqual(res_batch.content["accuracy_percent"], res_voice.content["accuracy_percent"])

    def test_input_immutability(self):
        ref_text = "  Exact string that must not be modified in place.  "
        ref_copy = str(ref_text)
        evaluator = AudioCandidateEvaluator(profile="voice_director")
        evaluator.evaluate(self.clean_wav_path, ref_text, direction={"target_wpm": 138})

        self.assertEqual(ref_text, ref_copy)


if __name__ == "__main__":
    unittest.main()
