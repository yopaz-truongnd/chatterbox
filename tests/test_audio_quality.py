"""Unit and Integration Tests for Audio Quality Evaluation, Auto-Fixing, QC & Batch Render Flow."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

from services.audio import auto_fix_audio_signal, evaluate_audio_signal, save_audio_wav
from services.batch_runner import BatchRunner
from services.job_manager import JobManager


class AudioQualityTestCase(unittest.TestCase):
    """Test suite for audio signal evaluation, loudness/silence auto-fixing, chunk reuse, and batch QC."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir_patch = patch.dict("os.environ", {"CHATTERBOX_API_DATA_DIR": self.temp_dir.name})
        self.data_dir_patch.start()

        self.jm = JobManager(
            project_dir=Path(self.temp_dir.name),
            data_dir=Path(self.temp_dir.name),
            device="cpu",
            cpu_threads=2,
        )
        self.runner = BatchRunner(self.jm)

    def tearDown(self):
        self.data_dir_patch.stop()
        self.temp_dir.cleanup()

    def test_evaluate_audio_signal_criteria(self):
        sr = 24000
        # 1. Standard healthy sine wave at -18 dB RMS
        t = torch.linspace(0, 1.0, sr)
        sine_wave = (0.177 * torch.sin(2 * 3.14159 * 440 * t)).unsqueeze(0)
        res = evaluate_audio_signal(sine_wave, sr)
        self.assertTrue(res["passed"])
        self.assertFalse(res["critical"])
        self.assertFalse(res["fixable"])
        self.assertEqual(res["duration_seconds"], 1.0)

        # 2. Empty tensor -> Critical Fail
        empty_res = evaluate_audio_signal(torch.zeros(1, 0), sr)
        self.assertFalse(empty_res["passed"])
        self.assertTrue(empty_res["critical"])

        # 3. Very loud / clipping wave -> Fixable
        clipped_wave = torch.ones(1, sr) * 1.5
        clip_res = evaluate_audio_signal(clipped_wave, sr)
        self.assertFalse(clip_res["passed"])
        self.assertTrue(clip_res["fixable"])

        # 4. Long leading & trailing silence
        padded_wave = torch.cat([
            torch.zeros(1, int(sr * 0.4)),
            sine_wave,
            torch.zeros(1, int(sr * 0.4)),
        ], dim=-1)
        silence_res = evaluate_audio_signal(padded_wave, sr)
        self.assertFalse(silence_res["passed"])
        self.assertTrue(silence_res["fixable"])
        self.assertTrue(silence_res["leading_silence_s"] >= 0.3)
        self.assertTrue(silence_res["trailing_silence_s"] >= 0.3)

    def test_auto_fix_audio_signal_pipeline(self):
        sr = 24000
        # Create wave with long silence (0.3s) and quiet loudness (-38 dB)
        t = torch.linspace(0, 1.0, sr)
        quiet_signal = (0.015 * torch.sin(2 * 3.14159 * 440 * t)).unsqueeze(0)
        noisy_raw = torch.cat([
            torch.zeros(1, int(sr * 0.3)),
            quiet_signal,
            torch.zeros(1, int(sr * 0.3)),
        ], dim=-1)

        fixed, actions, final_eval = auto_fix_audio_signal(noisy_raw, sr)

        self.assertIn("trim_silence", actions)
        self.assertIn("normalize_loudness", actions)
        self.assertTrue(final_eval["passed"])
        # Original duration was 1.6s, after trim with 50ms padding it should be ~1.1s
        self.assertTrue(final_eval["duration_seconds"] < 1.3)
        self.assertTrue(-22.0 <= final_eval["rms_db"] <= -14.0)

    def test_batch_runner_qc_and_quality_report_assembly(self):
        sr = 24000
        # Create mock audio with long silence
        t = torch.linspace(0, 0.8, int(sr * 0.8))
        raw_tensor = (0.1 * torch.sin(2 * 3.14159 * 440 * t)).unsqueeze(0)
        silence_padded = torch.cat([torch.zeros(1, int(sr * 0.3)), raw_tensor, torch.zeros(1, int(sr * 0.3))], dim=-1)

        with patch("services.job_manager.execute_model_inference", return_value=(silence_padded, sr)):
            job = self.jm.submit_job(
                job_type="batch",
                params={
                    "lines": [
                        {"idx": 0, "text": "Segment 1", "pause_duration": 0.2},
                        {"idx": 1, "text": "Segment 2", "pause_duration": 0.2},
                    ],
                    "model": "turbo",
                },
                input_paths=[],
            )
            out_wav = Path(self.temp_dir.name) / f"{job.id}.wav"
            ok, err = self.runner.run_batch_job(job, out_wav, in_process=True)
            self.assertTrue(ok)

            final_job = self.jm.get_job(job.id)
            self.assertEqual(final_job.status, "completed")
            bm = final_job.benchmark
            self.assertIn("quality_report", bm)
            self.assertTrue(bm["quality_report"]["passed"])
            self.assertEqual(bm["quality_report"]["total_segments"], 2)
            self.assertEqual(bm["quality_report"]["auto_fixed_segments"], 2)

            # Check individual line quality
            lines_res = bm["lines_results"]
            self.assertEqual(len(lines_res), 2)
            self.assertIn("quality", lines_res[0])
            self.assertIn("trim_silence", lines_res[0]["quality"]["actions"])

    def test_failed_qc_segment_is_not_merged_and_quality_report_fails(self):
        sr = 24000
        t = torch.linspace(0, 1.0, sr)
        good_tensor = (0.177 * torch.sin(2 * 3.14159 * 440 * t)).unsqueeze(0)
        unfixable_empty = torch.zeros(1, 0)

        def mock_infer(model_type, line_item, device):
            if line_item["idx"] == 0:
                return good_tensor, sr
            else:
                return unfixable_empty, sr

        with patch("services.job_manager.execute_model_inference", side_effect=mock_infer):
            job = self.jm.submit_job(
                job_type="batch",
                params={
                    "lines": [
                        {"idx": 0, "text": "Good segment", "pause_duration": 0.2},
                        {"idx": 1, "text": "Unfixable segment", "pause_duration": 0.2},
                    ],
                    "model": "turbo",
                },
                input_paths=[],
            )
            out_wav = Path(self.temp_dir.name) / f"{job.id}.wav"
            ok, err = self.runner.run_batch_job(job, out_wav, in_process=True)
            self.assertTrue(ok)

            final_job = self.jm.get_job(job.id)
            bm = final_job.benchmark
            qr = bm["quality_report"]
            self.assertFalse(qr["passed"])
            self.assertEqual(qr["passed_segments"], 1)
            self.assertEqual(qr["failed_segments"], 1)
            self.assertEqual(qr["total_segments"], 2)

            # Segment 1 must be failed and not merged
            self.assertEqual(bm["lines_results"][1]["status"], "failed")

    def test_silent_audio_and_short_duration_fail_qc(self):
        sr = 24000

        # 1. Complete silence must fail critically
        silent = torch.zeros(1, sr)
        eval_silent = evaluate_audio_signal(silent, sr)
        self.assertFalse(eval_silent["passed"])
        self.assertTrue(eval_silent["critical"])
        self.assertIn("Audio is silent or near-silent", eval_silent["issues"])

        # 2. Duration < 100ms must fail
        t_short = torch.linspace(0, 0.05, int(sr * 0.05))
        short_wave = (0.177 * torch.sin(2 * 3.14159 * 440 * t_short)).unsqueeze(0)
        eval_short = evaluate_audio_signal(short_wave, sr)
        self.assertFalse(eval_short["passed"])
        self.assertTrue(eval_short["critical"])

    def test_resume_chunk_truly_reuses_and_skips_inference(self):
        job = self.jm.submit_job(
            job_type="batch",
            params={
                "lines": [
                    {"idx": 0, "text": "Cached Line 1", "pause_duration": 0.2},
                    {"idx": 1, "text": "New Line 2", "pause_duration": 0.2},
                ],
                "model": "turbo",
                "resume": True,
            },
            input_paths=[],
        )

        # Pre-create valid line 0 chunk on disk
        chunks_dir = Path(self.temp_dir.name) / "chunks" / job.id
        chunks_dir.mkdir(parents=True, exist_ok=True)
        chunk0_path = chunks_dir / "line_0000.wav"
        sr = 24000
        t = torch.linspace(0, 1.0, sr)
        valid_wav = (0.177 * torch.sin(2 * 3.14159 * 440 * t)).unsqueeze(0)
        save_audio_wav(chunk0_path, valid_wav, sr)

        called_indices = []
        def mock_infer(model_type, line_item, device):
            called_indices.append(line_item["idx"])
            return valid_wav, sr

        with patch("services.job_manager.execute_model_inference", side_effect=mock_infer):
            out_wav = Path(self.temp_dir.name) / f"{job.id}.wav"
            ok, err = self.runner.run_batch_job(job, out_wav, in_process=True)
            self.assertTrue(ok)

            # Line 0 should be skipped from inference! Only Line 1 should be inferred.
            self.assertEqual(called_indices, [1])

            final_job = self.jm.get_job(job.id)
            self.assertEqual(final_job.status, "completed")
            self.assertEqual(len(final_job.benchmark["lines_results"]), 2)
            self.assertEqual(final_job.benchmark["lines_results"][0]["status"], "completed")

    def test_phase_change_emits_render_progress_without_progress_percent_increase(self):
        from services.event_bus import event_bus

        event_bus.clear()
        job = self.jm.submit_job(
            job_type="batch",
            params={"project_id": "proj_phase_test"},
            input_paths=[],
        )

        # 1. Emit evaluating at 50%
        self.jm._update_job_status(job.id, status="processing", phase="evaluating", progress_percent=50)
        # 2. Emit auto_fixing at SAME 50%
        self.jm._update_job_status(job.id, status="processing", phase="auto_fixing", progress_percent=50)

        events = event_bus.get_events(after_id=0, project_id="proj_phase_test")
        progress_events = [e for e in events if e["type"] == "render_progress"]
        self.assertEqual(len(progress_events), 2)
        self.assertEqual(progress_events[0]["data"]["phase"], "evaluating")
        self.assertEqual(progress_events[1]["data"]["phase"], "auto_fixing")


if __name__ == "__main__":
    unittest.main()
