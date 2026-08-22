"""Tests for Narration Planning, Pronunciation Scanner & Dictionary, ASR Content Critic, and Multi-Candidate Ranking."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import torch

from services.narration_planner import (
    scan_pronunciation_candidates,
    apply_pronunciation_dict,
    extract_emphasis_words,
    determine_segment_role_and_emotion,
    compile_narration_plan,
)
from services.critic import evaluate_speech_content
from services.project_script import segment_script_text


class NarrationPlanTestCase(unittest.TestCase):
    def test_scan_pronunciation_candidates(self):
        sample_text = (
            "[Narrator]: In 1984, NASA launched the Voyager probe into deep space. "
            "Professor Elan wondered if AI would ever comprehend the cosmic silence."
        )
        candidates = scan_pronunciation_candidates(sample_text)
        words = [c["word"] for c in candidates]

        self.assertIn("NASA", words)
        self.assertIn("1984", words)
        self.assertIn("Elan", words)

    def test_apply_pronunciation_dict(self):
        text = "Welcome to NASA. We explore AI frontiers at NASA headquarters."
        pron_dict = {"NASA": "N.A.S.A.", "AI": "A.I."}
        result = apply_pronunciation_dict(text, pron_dict)

        self.assertEqual(result, "Welcome to N.A.S.A.. We explore A.I. frontiers at N.A.S.A. headquarters.")

    def test_extract_emphasis_words(self):
        sent = "The door *slowly* opened, revealing a 'crucial' and extraordinary secret."
        emphasis = extract_emphasis_words(sent)
        self.assertIn("slowly", emphasis)
        self.assertIn("crucial", emphasis)
        self.assertIn("extraordinary", emphasis)

    def test_determine_segment_role_and_emotion(self):
        # 1. Narrator suspense
        role, emotion, energy = determine_segment_role_and_emotion("Narrator", "A shadow moved in the dark whisper.")
        self.assertEqual(role, "narrator")
        self.assertEqual(emotion, "suspense")
        self.assertLess(energy, 0.5)

        # 2. Dialogue energetic
        role, emotion, energy = determine_segment_role_and_emotion("Alice", "This is an amazing breakthrough, we are accelerating fast!")
        self.assertEqual(role, "dialogue")
        self.assertEqual(emotion, "energetic")
        self.assertGreater(energy, 0.7)

        # 3. Monologue thoughtful
        role, emotion, energy = determine_segment_role_and_emotion("Inner Thought", "I ponder what the future might bring.")
        self.assertEqual(role, "monologue")
        self.assertEqual(emotion, "thoughtful")

    def test_compile_narration_plan_and_segmentation(self):
        script_text = (
            "[Scene 1: Introduction]\n"
            "[Narrator]: Welcome to the world of quantum computing.\n"
            "[Alice]: We must hurry, the system is in critical condition!\n"
        )
        segments = segment_script_text(
            script_text,
            target_pace="medium",
            default_model="turbo",
            format_type="podcast",
            pronunciation_dict={"quantum": "kwan-tum"},
        )

        self.assertEqual(len(segments), 2)

        # Segment 1: Narrator
        seg1 = segments[0]
        self.assertEqual(seg1["speaker"], "Narrator")
        self.assertIn("narration_plan", seg1)
        plan1 = seg1["narration_plan"]
        self.assertEqual(plan1["role"], "narrator")
        self.assertEqual(plan1["model"], "turbo")
        self.assertEqual(plan1["candidate_strategy"], "multi_selective")  # has pronunciation override "quantum"

        # Segment 2: Dialogue
        seg2 = segments[1]
        self.assertEqual(seg2["speaker"], "Alice")
        plan2 = seg2["narration_plan"]
        self.assertEqual(plan2["role"], "dialogue")
        self.assertEqual(plan2["emotion"], "dramatic")
        self.assertEqual(plan2["candidate_strategy"], "multi_selective")  # dialogue triggers multi-candidate

    @patch("services.critic.transcribe_audio_whisper")
    def test_evaluate_speech_content_perfect_match(self, mock_transcribe):
        mock_transcribe.return_value = "The door slowly opened."
        ref = "The door slowly opened."

        # Synthetic 1-second audio tensor
        sr = 24000
        tensor = torch.zeros((1, sr), dtype=torch.float32)

        result = evaluate_speech_content(tensor, sr=sr, reference_text=ref, target_wpm=120)

        self.assertTrue(result["passed"])
        self.assertEqual(result["accuracy_percent"], 100.0)
        self.assertEqual(len(result["missing_words"]), 0)
        self.assertEqual(len(result["repeated_words"]), 0)
        self.assertGreaterEqual(result["score"], 90.0)

    @patch("services.job_manager.execute_model_inference")
    @patch("services.critic.transcribe_audio_whisper")
    def test_batch_runner_selective_candidates_and_ranking(self, mock_transcribe, mock_infer):
        import tempfile
        from pathlib import Path
        from services.batch_runner import BatchRunner
        from services.job_manager import JobManager

        mock_transcribe.return_value = "This is dialogue candidate"

        # Mock inference return audio: normal tone
        sr = 24000
        t = torch.linspace(0, 1.0, sr)
        audio = (0.177 * torch.sin(2 * 3.14159 * 440 * t)).unsqueeze(0)
        mock_infer.return_value = (audio, sr)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            with patch.dict("os.environ", {"CHATTERBOX_API_DATA_DIR": str(tmp_path)}):
                jm = JobManager(
                    project_dir=tmp_path,
                    data_dir=tmp_path,
                    device="cpu",
                    cpu_threads=2,
                )
                runner = BatchRunner(jm)

                line_item = {
                    "idx": 0,
                    "text": "This is dialogue candidate",
                    "speaker": "Alice",
                    "pause_duration": 0.5,
                    "narration_plan": {
                        "role": "dialogue",
                        "emotion": "dramatic",
                        "candidate_strategy": "multi_selective",
                        "target_wpm": 140,
                    },
                }

                job = jm.submit_job("batch", params={"lines": [line_item], "model": "turbo"}, input_paths=[])
                out_wav = tmp_path / f"{job.id}.wav"
                ok, err = runner.run_batch_job(job, out_wav, in_process=True)
                self.assertTrue(ok)

                updated_job = jm.get_job(job.id)
                self.assertEqual(updated_job.status, "completed")

                results = updated_job.benchmark.get("lines_results", [])
                self.assertEqual(len(results), 1)
                seg_res = results[0]

                # Verify 2 candidates were attempted
                attempts = seg_res.get("attempts", [])
                self.assertEqual(len(attempts), 2)
                self.assertTrue(any(a.get("selected") for a in attempts))
                self.assertIn("content_evaluation", seg_res)
                self.assertTrue(seg_res["content_evaluation"]["passed"])


if __name__ == "__main__":
    unittest.main()


