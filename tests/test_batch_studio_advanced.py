import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import torch
from fastapi.testclient import TestClient

import api_app
from unittest.mock import patch

from services.audio import (
    apply_edge_fades,
    merge_speech_segments,
    mix_background_music,
    normalize_loudness,
)
from utils.file_importer import (
    parse_csv_script,
    parse_markdown_script,
    parse_multicharacter_script,
    parse_srt_or_vtt,
    parse_timestamp_to_seconds,
)
from utils.text_cleaner import split_into_sentences


class BatchStudioAdvancedTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["CHATTERBOX_IN_PROCESS"] = "1"
        cls.temp_dir = tempfile.TemporaryDirectory()
        api_app.API_DATA_DIR = Path(cls.temp_dir.name)
        cls.data_dir = api_app.API_DATA_DIR
        cls.client_context = TestClient(api_app.app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        cls.temp_dir.cleanup()

    def setUp(self):
        self.mock_inference_patcher = patch(
            "services.job_manager.execute_model_inference",
            return_value=(torch.zeros(1, 2400), 24000),
        )
        self.mock_inference_patcher.start()
        self.addCleanup(self.mock_inference_patcher.stop)

        if api_app.job_manager:
            api_app.job_manager._job_queue.join()
            with api_app.job_manager._jobs_lock:
                api_app.job_manager._jobs.clear()
            for output_path in api_app.API_DATA_DIR.joinpath("outputs").glob("*"):
                if output_path.is_file():
                    output_path.unlink()
                elif output_path.is_dir():
                    shutil.rmtree(output_path, ignore_errors=True)


    def test_sentence_split_preserves_punctuation_and_no_orphan_rows(self):
        text = "Xin chào! Bạn có khỏe không? Tôi rất khỏe... Thật tuyệt vời!"
        sentences = split_into_sentences(text)
        self.assertEqual(len(sentences), 4)
        self.assertEqual(sentences[0], "Xin chào!")
        self.assertEqual(sentences[1], "Bạn có khỏe không?")
        self.assertEqual(sentences[2], "Tôi rất khỏe...")
        self.assertEqual(sentences[3], "Thật tuyệt vời!")

        # Verify lone punctuation string doesn't create orphan row
        text_with_orphans = "Câu một. ... ??? Câu hai!"
        s2 = split_into_sentences(text_with_orphans)
        for s in s2:
            self.assertTrue(any(c.isalnum() for c in s), f"Orphan punctuation found: '{s}'")

    def test_timestamp_parser(self):
        self.assertAlmostEqual(parse_timestamp_to_seconds("00:01:23.456"), 83.456)
        self.assertAlmostEqual(parse_timestamp_to_seconds("00:02:10,500"), 130.500)
        self.assertAlmostEqual(parse_timestamp_to_seconds("45.2"), 45.2)

    def test_srt_and_vtt_parser(self):
        srt_content = """1
00:00:01,000 --> 00:00:04,500
Xin chào các bạn.

2
00:00:05,200 --> 00:00:08,000
<font color="#fff">Đây là phụ đề mẫu.</font>
"""
        parsed = parse_srt_or_vtt(srt_content)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["text"], "Xin chào các bạn.")
        self.assertEqual(parsed[0]["start_seconds"], 1.0)
        self.assertEqual(parsed[0]["end_seconds"], 4.5)
        self.assertEqual(parsed[1]["text"], "Đây là phụ đề mẫu.")

    def test_csv_parser(self):
        csv_content = """speaker,text,pause
Narrator,"Ngày xửa ngày xưa ở một khu rừng nọ",1.2
Sarah,"Chào bạn, tôi là Sarah!",0.5
"""
        parsed = parse_csv_script(csv_content)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["speaker"], "Narrator")
        self.assertEqual(parsed[0]["pause_duration"], 1.2)
        self.assertEqual(parsed[1]["speaker"], "Sarah")

    def test_markdown_parser(self):
        md_content = """# Tiêu đề chương 1

Đây là đoạn văn bản mở đầu có [liên kết](https://example.com) và **chữ đậm**.

```python
print("code block to ignore")
```

- Ý thứ nhất
- Ý thứ hai
"""
        parsed = parse_markdown_script(md_content, use_headings_as_chapters=True)
        self.assertTrue(len(parsed) >= 2)
        self.assertTrue(any("Tiêu đề chương 1" in p["text"] for p in parsed))
        self.assertTrue(any("Đây là đoạn văn bản mở đầu có liên kết và chữ đậm." in p["text"] for p in parsed))
        # Ensure code block was removed
        self.assertFalse(any("code block to ignore" in p["text"] for p in parsed))

    def test_multicharacter_script_parser(self):
        script = """[Narrator]: Ngày xửa ngày xưa...
[Sarah (vui vẻ)]: Xin chào mọi người!
John: Tôi cũng rất vui được tham gia.
Đoạn thoại không có nhân vật đứng trước."""
        parsed = parse_multicharacter_script(script)
        self.assertEqual(len(parsed), 4)
        self.assertEqual(parsed[0]["speaker"], "Narrator")
        self.assertEqual(parsed[0]["text"], "Ngày xửa ngày xưa...")
        self.assertEqual(parsed[1]["speaker"], "Sarah")
        self.assertEqual(parsed[1]["emotion"], "vui vẻ")
        self.assertEqual(parsed[1]["text"], "Xin chào mọi người!")
        self.assertEqual(parsed[2]["speaker"], "John")
        self.assertEqual(parsed[2]["text"], "Tôi cũng rất vui được tham gia.")
        self.assertNotIn("speaker", parsed[3])
        self.assertEqual(parsed[3]["text"], "Đoạn thoại không có nhân vật đứng trước.")

    def test_loudness_normalization_and_fades(self):
        sr = 24000
        # Create silent/low tensor
        wav = torch.sin(torch.linspace(0, 440 * 2 * 3.14159, sr * 2)).unsqueeze(0) * 0.05
        norm_wav = normalize_loudness(wav, target_db=-20.0, peak_limit=0.95)
        self.assertLessEqual(torch.max(torch.abs(norm_wav)).item(), 0.950001)

        faded_wav = apply_edge_fades(norm_wav, fade_samples=480)
        self.assertEqual(faded_wav.shape, norm_wav.shape)
        # First sample should be close to 0
        self.assertAlmostEqual(faded_wav[0, 0].item(), 0.0, places=3)

    def test_merge_speech_segments_with_per_line_pauses(self):
        sr = 24000
        seg1 = torch.zeros((1, sr * 1))
        seg2 = torch.zeros((1, sr * 1))
        merged = merge_speech_segments(
            [seg1, seg2],
            pause_duration=0.5,
            pause_durations=[1.0, 0.5],
            target_sr=sr,
            normalize=False,
            crossfade_ms=0,
        )
        # Length should be seg1(1s) + pause1(1s) + seg2(1s) = 3s = 72000 samples
        self.assertEqual(merged.shape[-1], 3 * sr)

    def test_bgm_ducking(self):
        sr = 24000
        speech = torch.sin(torch.linspace(0, 440 * 2 * 3.14159, sr * 2)).unsqueeze(0) * 0.5
        bgm_path = self.data_dir / "test_bgm.wav"
        from services.audio import save_audio_wav
        save_audio_wav(bgm_path, torch.sin(torch.linspace(0, 220 * 2 * 3.14159, sr * 3)).unsqueeze(0) * 0.4, sr)

        mixed, err = mix_background_music(speech, bgm_path, bgm_volume=0.3, target_sr=sr, ducking=True)
        self.assertIsNotNone(mixed)
        self.assertIsNone(err)
        self.assertEqual(mixed.shape[-1], speech.shape[-1])

    def test_batch_zip_export_endpoint(self):
        # Create a fake completed batch job in DB and disk
        from job_store import AudioJob
        from services.audio import save_audio_wav

        job_id = "test_batch_zip_job"
        job_dir = self.data_dir / "outputs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        out_wav = job_dir / "output.wav"
        out_srt = job_dir / "output.srt"
        chunks_dir = self.data_dir / "chunks" / job_id
        chunks_dir.mkdir(parents=True, exist_ok=True)
        line_wav = chunks_dir / "line_0000.wav"

        sr = 24000
        dummy_wav = torch.zeros((1, sr))
        save_audio_wav(out_wav, dummy_wav, sr)
        save_audio_wav(line_wav, dummy_wav, sr)
        with open(out_srt, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,000 --> 00:00:01,000\nTest Subtitle\n")

        job = AudioJob(
            id=job_id,
            type="batch",
            params={"model": "nano", "lines": [{"idx": 0, "text": "Test Line"}]},
            input_paths=[],
            status="completed",
            output_path=str(out_wav),
            created_at="2026-08-20T12:00:00",
            duration_seconds=1.0,
        )
    def test_voice_conditionals_reset_between_batch_lines(self):
        """Verify that lines without audio_prompt_path restore default conditionals and don't inherit previous line's voice."""
        from unittest.mock import MagicMock
        from services.inference import generate_with_model

        class DummyModel:
            def __init__(self):
                self.default_conds = {"voice": "default_voice_sample"}
                self.conds = {"voice": "default_voice_sample"}
                self.history = []

            def generate(self, text, audio_prompt_path=None, **kwargs):
                if audio_prompt_path:
                    self.conds = {"voice": f"custom_{Path(audio_prompt_path).stem}"}
                self.history.append((text, self.conds["voice"]))
                return torch.zeros(1, 2400)

        model = DummyModel()
        lines = [
            {"text": "Line 1 Char A", "audio_prompt_path": "/path/to/charA.wav"},
            {"text": "Line 2 Default", "audio_prompt_path": None},
            {"text": "Line 3 Char B", "audio_prompt_path": "/path/to/charB.wav"},
            {"text": "Line 4 Default", "audio_prompt_path": None},
        ]

        for line in lines:
            generate_with_model(model, "nano", line, "cpu")

        self.assertEqual(len(model.history), 4)
        self.assertEqual(model.history[0], ("Line 1 Char A", "custom_charA"))
        self.assertEqual(model.history[1], ("Line 2 Default", "default_voice_sample"))
        self.assertEqual(model.history[2], ("Line 3 Char B", "custom_charB"))
        self.assertEqual(model.history[3], ("Line 4 Default", "default_voice_sample"))

    def test_batch_rejects_nonexistent_character_with_422(self):
        """Batch submission with deleted or invalid Character ID must return 422 Unprocessable Entity."""
        payload = {
            "lines": [
                {"text": "Line 1 valid text", "character_id": "non_existent_character_99999"}
            ]
        }
        res = self.client.post("/api/v1/tts/batch", json=payload)
        self.assertEqual(res.status_code, 422)
        self.assertIn("non_existent_character_99999", res.json()["detail"])

    def test_batch_preserves_retry_metadata(self):
        """Batch created as a retry/resume must store parent_batch_id and retry_of_indices in params."""
        payload = {
            "lines": [{"idx": 3, "text": "Line 3 retry"}, {"idx": 7, "text": "Line 7 retry"}],
            "parent_batch_id": "batch_parent_abc123",
            "retry_of_indices": [3, 7],
        }
        res = self.client.post("/api/v1/tts/batch", json=payload)
        self.assertEqual(res.status_code, 202)
        data = res.json()
        self.assertEqual(data["params"]["parent_batch_id"], "batch_parent_abc123")
        self.assertEqual(data["params"]["retry_of_indices"], [3, 7])

    def test_delete_job_artifacts_removes_all_files(self):
        """Job deletion must remove audio, subtitles, zip package, metadata JSON, configs, and chunks directory."""
        from job_store import AudioJob, delete_job_artifacts

        job_id = "test_cleanup_artifacts_job"
        wav_path = self.data_dir / "outputs" / f"{job_id}.wav"
        srt_path = self.data_dir / "outputs" / f"{job_id}.srt"
        zip_path = self.data_dir / "outputs" / f"{job_id}.zip"
        json_path = self.data_dir / "outputs" / f"{job_id}.json"
        cfg_path = self.data_dir / "configs" / f"{job_id}.json"
        chunks_dir = self.data_dir / "chunks" / job_id
        chunks_dir.mkdir(parents=True, exist_ok=True)
        chunk_file = chunks_dir / "line_0000.wav"

        # Create all artifact files
        for p in [wav_path, srt_path, zip_path, json_path, cfg_path, chunk_file]:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("test artifact", encoding="utf-8")

        job = AudioJob(
            id=job_id,
            type="batch",
            params={},
            input_paths=[],
            status="completed",
            output_path=str(wav_path),
        )
        api_app.job_manager.store.save(job)
        with api_app.job_manager._jobs_lock:
            api_app.job_manager._jobs[job_id] = job

        deleted = api_app.job_manager.delete_job(job_id)
        self.assertTrue(deleted)

        self.assertFalse(wav_path.exists())
        self.assertFalse(srt_path.exists())
        self.assertFalse(zip_path.exists())
        self.assertFalse(json_path.exists())
        self.assertFalse(cfg_path.exists())
        self.assertFalse(chunks_dir.exists())

    def test_zip_caching_and_atomic_creation(self):
        """Second request to ZIP endpoint should return cached zip without rebuilding."""
        from job_store import AudioJob
        from services.audio import save_audio_wav
        import time

        job_id = "test_zip_caching_job"
        out_wav = self.data_dir / "outputs" / f"{job_id}.wav"
        chunks_dir = self.data_dir / "chunks" / job_id
        chunks_dir.mkdir(parents=True, exist_ok=True)
        save_audio_wav(out_wav, torch.zeros(1, 24000), 24000)

        job = AudioJob(
            id=job_id,
            type="batch",
            params={},
            input_paths=[],
            status="completed",
            output_path=str(out_wav),
            created_at="2026-08-20T12:00:00",
        )
        api_app.job_manager.store.save(job)
        with api_app.job_manager._jobs_lock:
            api_app.job_manager._jobs[job_id] = job

        res1 = self.client.get(f"/api/v1/jobs/{job_id}/zip")
        self.assertEqual(res1.status_code, 200)
        zip_path = self.data_dir / "outputs" / f"{job_id}.zip"
        self.assertTrue(zip_path.exists())
        first_mtime = zip_path.stat().st_mtime

        time.sleep(0.05)
        res2 = self.client.get(f"/api/v1/jobs/{job_id}/zip")
        self.assertEqual(res2.status_code, 200)
        second_mtime = zip_path.stat().st_mtime
        self.assertEqual(first_mtime, second_mtime)

    def test_pause_alignment_when_line_fails(self):
        """When line 0 fails (pause 2.0s), line 1 (pause 0.3s) and line 2 succeed, verify pause between line 1 and 2 is 0.3s."""
        sr = 24000
        # Line 1 audio: 1.0s (24000 samples), Line 2 audio: 1.0s (24000 samples)
        wav1 = torch.ones(1, sr) * 0.5
        wav2 = torch.ones(1, sr) * 0.5

        # Successful pauses should only contain line 1 (0.3s) and line 2 (0.8s)
        merged = merge_speech_segments(
            [wav1, wav2],
            pause_duration=0.8,
            pause_durations=[0.3, 0.8],
            target_sr=sr,
            normalize=False,
            crossfade_ms=0,
        )
        # Expected duration: 1.0s + 0.3s + 1.0s = 2.3s = 55200 samples
        expected_samples = int(sr * 1.0 + sr * 0.3 + sr * 1.0)
        self.assertEqual(merged.shape[-1], expected_samples)

        # Check silence in middle
        silence_segment = merged[0, sr:sr + int(sr * 0.3)]
        self.assertTrue(torch.all(silence_segment == 0.0))

    def test_strict_original_timeline_policy(self):
        """When keep_original_timeline is enabled, start_seconds and end_seconds must strictly match original."""
        from job_store import AudioJob
        job_id = "test_strict_timeline_job"
        out_wav = self.data_dir / "outputs" / f"{job_id}.wav"
        lines = [
            {"idx": 0, "text": "Line 1", "start_seconds": 1.0, "end_seconds": 2.0},
            {"idx": 1, "text": "Line 2", "start_seconds": 3.5, "end_seconds": 5.0},
        ]
        job = AudioJob(
            id=job_id,
            type="batch",
            params={"model": "nano", "lines": lines, "keep_original_timeline": True, "export_srt": True},
            input_paths=[],
            status="pending",
        )
        api_app.job_manager.store.save(job)
        with api_app.job_manager._jobs_lock:
            api_app.job_manager._jobs[job_id] = job

        success, err = api_app.job_manager._run_batch_job(job, out_wav, in_process=True)
        self.assertTrue(success)

        saved_job = api_app.job_manager.store.get(job_id)
        r0 = saved_job.benchmark["lines_results"][0]
        r1 = saved_job.benchmark["lines_results"][1]
        self.assertEqual(r0["start_seconds"], 1.0)
        self.assertEqual(r0["end_seconds"], 2.0)
        self.assertEqual(r1["start_seconds"], 3.5)
        self.assertEqual(r1["end_seconds"], 5.0)

        srt_path = out_wav.with_suffix(".srt")
        self.assertTrue(srt_path.exists())
        srt_content = srt_path.read_text(encoding="utf-8")
        self.assertIn("00:00:01,000 --> 00:00:02,000", srt_content)
        self.assertIn("00:00:03,500 --> 00:00:05,000", srt_content)

    def test_partial_failure_in_public_dict(self):
        """Failed lines must not have audio_url and must preserve status='failed'."""
        from job_store import AudioJob
        job_id = "test_partial_failure_job"
        job = AudioJob(
            id=job_id,
            type="batch",
            params={"model": "nano", "lines": [{"idx": 0, "text": "Ok"}, {"idx": 1, "text": "Bad"}]},
            input_paths=[],
            status="completed",
            benchmark={
                "lines_results": [
                    {"idx": 0, "status": "completed", "duration_seconds": 1.5},
                    {"idx": 1, "status": "failed", "duration_seconds": 0.0, "error": "CUDA OOM"},
                ]
            },
        )
        pub = job.public_dict()
        self.assertIn("lines_results", pub)
        res0 = pub["lines_results"][0]
        res1 = pub["lines_results"][1]

        self.assertEqual(res0["status"], "completed")
        self.assertEqual(res0["audio_url"], f"/api/v1/jobs/{job_id}/lines/0")

    def test_subprocess_runner_batch_execution(self):
        """Simulate subprocess batch runner execution and verify benchmark generation without NameError."""
        from inference_runner import run_batch_inference
        from unittest.mock import patch, MagicMock

        mock_model = MagicMock()
        dummy_wav = torch.zeros(1, 24000)

        job_id = "test_subproc_batch_runner"
        out_wav = self.data_dir / "outputs" / f"{job_id}.wav"
        meta_json = self.data_dir / "outputs" / f"{job_id}.json"
        chunks_dir = self.data_dir / "chunks" / job_id
        chunks_dir.mkdir(parents=True, exist_ok=True)

        config = {
            "type": "batch",
            "model": "nano",
            "device": "cpu",
            "output_path": str(out_wav),
            "meta_path": str(meta_json),
            "chunks_dir": str(chunks_dir),
            "pause_duration": 0.5,
            "export_srt": True,
            "lines": [
                {"idx": 0, "text": "Line 1 valid"},
                {"idx": 1, "text": "Line 2 valid"},
            ],
        }

        with patch("inference_runner.load_model", return_value=(mock_model, 24000)), \
             patch("inference_runner.generate_with_model", return_value=dummy_wav):
            run_batch_inference(config)

        self.assertTrue(out_wav.exists())
        self.assertTrue(meta_json.exists())
        self.assertTrue(out_wav.with_suffix(".srt").exists())

        with open(meta_json, "r", encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual(meta["completed_lines"], 2)
        self.assertEqual(meta["failed_lines"], 0)

    def test_recursive_sanitizer_removes_all_internal_paths(self):
        """Job public_dict must recursively purge any internal paths from top-level params, lines, and lines_results."""
        from job_store import AudioJob
        job_id = "test_path_leak_job"
        job = AudioJob(
            id=job_id,
            type="batch",
            params={
                "model": "nano",
                "bgm_audio_path": "/var/www/chatterbox/data/bgm.wav",
                "chunks_dir": "/var/www/chatterbox/data/chunks/xyz",
                "lines": [
                    {
                        "idx": 0,
                        "text": "Hello world",
                        "audio_prompt_path": "/private/var/www/chatterbox/data/voices/ref.wav",
                        "character_id": "hero_01",
                    }
                ],
            },
            input_paths=["/private/var/www/chatterbox/input.wav"],
            output_path="/private/var/www/chatterbox/outputs/out.wav",
            status="completed",
            benchmark={
                "device": "cpu",
                "meta_path": "/private/var/www/chatterbox/meta.json",
                "lines_results": [
                    {
                        "idx": 0,
                        "status": "completed",
                        "duration_seconds": 1.2,
                        "audio_path": "/private/var/www/chatterbox/chunks/line_0000.wav",
                    }
                ],
            },
        )
        pub = job.public_dict()

        # Convert to json string and check no internal path keys or path values leak
        raw_json = json.dumps(pub)
        self.assertNotIn("audio_prompt_path", raw_json)
        self.assertNotIn("bgm_audio_path", raw_json)
        self.assertNotIn("chunks_dir", raw_json)
        self.assertNotIn("audio_path", raw_json)
        self.assertNotIn("input_paths", raw_json)
        self.assertNotIn("output_path", raw_json)
        self.assertNotIn("meta_path", raw_json)

        # Check line text and character_id are preserved
        self.assertEqual(pub["params"]["lines"][0]["character_id"], "hero_01")
        self.assertEqual(pub["params"]["lines"][0]["text"], "Hello world")
        self.assertEqual(pub["lines_results"][0]["audio_url"], f"/api/v1/jobs/{job_id}/lines/0")

    def test_subprocess_runner_real_process_execution_with_special_paths(self):
        """Run real inference_runner.py subprocess with a config path containing spaces and special symbols."""
        import subprocess

        job_id = "test_real_subproc_job"
        special_dir = self.data_dir / "Special Folder with Spaces & Dấu Tiếng Việt"
        special_dir.mkdir(parents=True, exist_ok=True)
        out_wav = special_dir / f"{job_id} merged output.wav"
        meta_json = special_dir / f"{job_id} benchmark meta.json"
        chunks_dir = special_dir / f"chunks {job_id}"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        cfg_file = special_dir / f"config file for {job_id}.json"

        config = {
            "type": "batch",
            "model": "nano",
            "device": "cpu",
            "output_path": str(out_wav),
            "meta_path": str(meta_json),
            "chunks_dir": str(chunks_dir),
            "pause_duration": 0.4,
            "export_srt": True,
            "lines": [
                {"idx": 0, "text": "Dòng 1: Thử nghiệm tiến trình con với đường dẫn có dấu cách."},
                {"idx": 1, "text": "Dòng 2: Hoàn tất kiểm tra CLI argument và UTF-8 serialization."},
            ],
        }

        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        env = os.environ.copy()
        env["CHATTERBOX_TEST_DUMMY_INFERENCE"] = "1"
        env["PYTHONPATH"] = str(ROOT_DIR)

        proc = subprocess.run(
            [sys.executable, str(ROOT_DIR / "inference_runner.py"), "--config", str(cfg_file)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            timeout=15,
        )

        self.assertEqual(proc.returncode, 0, f"Subprocess failed with stderr: {proc.stderr}")
        self.assertIn("PROGRESS:", proc.stdout)
        self.assertIn("BENCHMARK:", proc.stdout)
        self.assertTrue(out_wav.exists())
        self.assertTrue(meta_json.exists())
        self.assertTrue(out_wav.with_suffix(".srt").exists())

        with open(meta_json, "r", encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual(meta["completed_lines"], 2)
        self.assertEqual(meta["failed_lines"], 0)


if __name__ == "__main__":
    unittest.main()

