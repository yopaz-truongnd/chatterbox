import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import torch
from fastapi.testclient import TestClient

import api_app
from job_store import AudioJob, JobStore
from services.job_manager import JobManager


class FakeModel:
    sr = 24000

    def generate(self, *args, **kwargs):
        return torch.zeros(1, 240)


class FailingModel:
    sr = 24000

    def generate(self, *args, **kwargs):
        raise RuntimeError("inference failed")


class ApiAppTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["CHATTERBOX_IN_PROCESS"] = "1"
        cls.temp_dir = tempfile.TemporaryDirectory()
        api_app.API_DATA_DIR = Path(cls.temp_dir.name)
        cls.client_context = TestClient(api_app.app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        cls.temp_dir.cleanup()

    def setUp(self):
        if api_app.job_manager:
            api_app.job_manager._job_queue.join()
            with api_app.job_manager._jobs_lock:
                api_app.job_manager._jobs.clear()
            for output_path in api_app.API_DATA_DIR.joinpath("outputs").glob("*.wav"):
                output_path.unlink()

    def wait_for_job(self, job_id, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            response = self.client.get(f"/api/v1/jobs/{job_id}")
            self.assertEqual(response.status_code, 200)
            job = response.json()
            if job["status"] in {"completed", "failed", "cancelled"}:
                return job
            time.sleep(0.02)
        self.fail(f"Job {job_id} did not finish within {timeout} seconds")

    def test_health_reports_resource_policy(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["cpu_threads"], 2)
        self.assertEqual(payload["default_model"], api_app.RECOMMENDED_MODEL)
        self.assertEqual(payload["recommended_model"], api_app.RECOMMENDED_MODEL)
        self.assertIn("models_cached", payload)

    def test_quality_presets_endpoint(self):
        response = self.client.get("/api/v1/presets/quality")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("presets", data)
        self.assertIn("fast", data["presets"])
        self.assertIn("balanced", data["presets"])
        self.assertIn("expressive", data["presets"])

    def test_diagnostics_endpoint(self):
        response = self.client.get("/api/v1/diagnostics")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("os", data)
        self.assertIn("platform", data)
        self.assertIn("python", data)
        self.assertIn("torch", data)
        self.assertIn("device", data)
        self.assertIn("ram_total_gb", data)
        self.assertIn("recommended_model", data)
        self.assertIn("data_dir", data)
        self.assertIn("checkpoints", data)

    def test_openapi_contains_public_endpoints(self):
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        paths = response.json()["paths"]
        expected_paths = {
            "/api/v1/text/split",
            "/api/v1/tts",
            "/api/v1/tts/turbo",
            "/api/v1/tts/standard",
            "/api/v1/tts/multilingual",
            "/api/v1/tts/long-text",
            "/api/v1/presets/quality",
            "/api/v1/diagnostics",
            "/api/v1/voice-conversion",
            "/api/v1/characters",
            "/api/v1/characters/{character_id}",
            "/api/v1/models",
            "/api/v1/jobs",
            "/api/v1/jobs/{job_id}",
            "/api/v1/jobs/{job_id}/cancel",
            "/api/v1/jobs/{job_id}/audio",
            "/api/v1/audio/merge",
        }
        self.assertTrue(expected_paths.issubset(paths))

    def test_split_text_preserves_unicode_and_whitespace(self):
        text = (
            "First sentence keeps punctuation and spaces.  " * 8
            + "\n\nUnicode remains unchanged: Tiếng Việt, 日本語, العربية. "
            + "Final words without normalization. " * 12
        )
        response = self.client.post(
            "/api/v1/text/split",
            json={"text": text, "min_chars": 200, "max_chars": 500},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        chunks = payload["chunks"]
        self.assertTrue(payload["content_preserved"])
        self.assertEqual("".join(chunk["text"] for chunk in chunks), text)
        self.assertTrue(all(len(chunk["text"]) <= 500 for chunk in chunks))
        self.assertTrue(all(len(chunk["text"]) >= 200 for chunk in chunks[:-1]))
        for chunk in chunks:
            self.assertEqual(chunk["text"], text[chunk["start"]:chunk["end"]])

    def test_split_text_rejects_invalid_range(self):
        response = self.client.post(
            "/api/v1/text/split",
            json={"text": "A valid input", "min_chars": 600, "max_chars": 500},
        )
        self.assertEqual(response.status_code, 422)

    def test_default_tts_uses_recommended_model_and_downloads_wav(self):
        with patch("services.job_manager.execute_model_inference", return_value=(torch.zeros(1, 240), 24000)):
            response = self.client.post(
                "/api/v1/tts",
                data={"text": "Hello from the default endpoint."},
            )
            self.assertEqual(response.status_code, 202, response.text)
            submitted = response.json()
            self.assertEqual(submitted["type"], api_app.RECOMMENDED_MODEL)

            completed = self.wait_for_job(submitted["id"])

        self.assertEqual(completed["status"], "completed")
        self.assertNotIn("audio_prompt_path", completed["params"])
        audio = self.client.get(completed["audio_url"])
        self.assertEqual(audio.status_code, 200)
        self.assertEqual(audio.headers["content-type"], "audio/wav")
        self.assertGreater(len(audio.content), 0)

    def test_cancel_job_sets_status_cancelled(self):
        with patch("services.job_manager.execute_model_inference", return_value=(torch.zeros(1, 240), 24000)):
            response = self.client.post("/api/v1/tts", data={"text": "Job to be cancelled."})
            self.assertEqual(response.status_code, 202)
            job_id = response.json()["id"]

            cancel_res = self.client.post(f"/api/v1/jobs/{job_id}/cancel")
            self.assertEqual(cancel_res.status_code, 200)
            self.assertEqual(cancel_res.json()["status"], "cancelled")

    def test_long_text_batch_synthesis(self):
        with patch("services.job_manager.execute_model_inference", return_value=(torch.zeros(1, 240), 24000)):
            long_content = "Đoạn văn thứ nhất dùng để kiểm tra tính năng đọc truyện. " * 10
            response = self.client.post(
                "/api/v1/tts/long-text",
                data={"text": long_content, "min_chars": 100, "max_chars": 250, "pause_duration": 0.3},
            )
            self.assertEqual(response.status_code, 202)
            job_id = response.json()["id"]
            completed = self.wait_for_job(job_id, timeout=6)
            self.assertEqual(completed["status"], "completed")
            self.assertIsNotNone(completed["audio_url"])

    def test_voice_conversion_cleans_uploaded_files(self):
        with patch("services.job_manager.execute_model_inference", return_value=(torch.zeros(1, 240), 24000)):
            response = self.client.post(
                "/api/v1/voice-conversion",
                files={
                    "source_audio": ("source.wav", b"fake-source", "audio/wav"),
                    "target_voice": ("target.wav", b"fake-target", "audio/wav"),
                },
            )
            self.assertEqual(response.status_code, 202, response.text)
            completed = self.wait_for_job(response.json()["id"])

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(list(api_app.API_DATA_DIR.joinpath("inputs").iterdir()), [])

    def test_failed_inference_marks_job_failed(self):
        def failing_inference(*args, **kwargs):
            raise RuntimeError("inference failed")

        with patch("services.job_manager.execute_model_inference", side_effect=failing_inference):
            response = self.client.post("/api/v1/tts", data={"text": "This job fails."})
            self.assertEqual(response.status_code, 202)
            failed = self.wait_for_job(response.json()["id"])

        self.assertEqual(failed["status"], "failed")
        self.assertIn("inference failed", failed["error"])
        self.assertIsNone(failed["audio_url"])

    def test_settings_validation_rejects_unknown_fields(self):
        with patch("config.settings.settings_manager.save") as mock_save:
            # Valid update with restart_required key
            response = self.client.post("/api/v1/settings", json={"retention_days": 7, "dark_mode": True})
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "ok")
            self.assertTrue(data["restart_required"])
            self.assertEqual(data["settings"]["retention_days"], 7)
            self.assertTrue(mock_save.called)

            # Invalid field rejected
            bad_response = self.client.post("/api/v1/settings", json={"unrecognized_hacker_key": "injected"})
            self.assertEqual(bad_response.status_code, 422)

    def test_startup_recovers_hanging_jobs(self):
        # Create a JobManager with pre-existing queued and processing jobs in SQLite
        temp_d = tempfile.TemporaryDirectory()
        try:
            db_dir = Path(temp_d.name)
            store = JobStore(db_dir / "jobs.db")
            store.save(AudioJob(id="stuck_queued", type="nano", params={"text": "hi"}, input_paths=[], status="queued", phase="queued", created_at="2026-08-20T00:00:00Z"))
            store.save(AudioJob(id="stuck_processing", type="turbo", params={"text": "hi"}, input_paths=[], status="processing", phase="generating_tokens", created_at="2026-08-20T00:00:00Z"))

            mgr = JobManager(data_dir=db_dir, project_dir=api_app.PROJECT_DIR, device="cpu", cpu_threads=2)
            mgr.startup()
            try:
                j1 = mgr.get_job("stuck_queued")
                j2 = mgr.get_job("stuck_processing")
                self.assertEqual(j1.status, "failed")
                self.assertEqual(j1.phase, "failed")
                self.assertIn("API restarted before job completed", j1.error)
                self.assertEqual(j2.status, "failed")
                self.assertEqual(j2.phase, "failed")
                self.assertIn("API restarted before job completed", j2.error)
            finally:
                mgr.shutdown()
        finally:
            temp_d.cleanup()

    def test_completed_job_can_be_filtered_and_deleted(self):
        with patch("services.job_manager.execute_model_inference", return_value=(torch.zeros(1, 240), 24000)):
            response = self.client.post("/api/v1/tts", data={"text": "Delete this output."})
            completed = self.wait_for_job(response.json()["id"])

        jobs = self.client.get("/api/v1/jobs", params={"status": "completed"}).json()
        self.assertGreaterEqual(jobs["count"], 1)

        deleted = self.client.delete(f"/api/v1/jobs/{completed['id']}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get(f"/api/v1/jobs/{completed['id']}").status_code, 404)

    def test_clean_temp_dir_rejects_409_when_jobs_active(self):
        # Mock an active running job in job_manager
        with patch.object(api_app.job_manager, "_active_procs", {"job_123": None}):
            response = self.client.post("/api/v1/system/clean-tmp")
            self.assertEqual(response.status_code, 409)
            self.assertIn("đang có 1 tác vụ", response.json()["detail"])

    def test_clean_temp_dir_succeeds_when_idle(self):
        response = self.client.post("/api/v1/system/clean-tmp")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_batch_tts_endpoint_processes_multiple_lines_and_generates_srt(self):
        with patch("services.job_manager.execute_model_inference", return_value=(torch.zeros(1, 2400), 24000)):
            lines = [
                {"idx": 0, "text": "Dòng thứ nhất kịch bản."},
                {"idx": 1, "text": "Dòng thứ hai đối thoại."},
            ]
            response = self.client.post(
                "/api/v1/tts/batch",
                json={
                    "lines": lines,
                    "model": "nano",
                    "pause_duration": 0.5,
                    "export_srt": True,
                },
            )
            self.assertEqual(response.status_code, 202)
            job_id = response.json()["id"]
            completed = self.wait_for_job(job_id, timeout=6)
            self.assertEqual(completed["status"], "completed")
            self.assertIsNotNone(completed["audio_url"])
            self.assertIsNotNone(completed["srt_url"])
            self.assertEqual(len(completed["lines_results"]), 2)

            # Test line audio download
            line0_res = self.client.get(f"/api/v1/jobs/{job_id}/lines/0")
            self.assertEqual(line0_res.status_code, 200)
            self.assertEqual(line0_res.headers["content-type"], "audio/wav")

            # Test SRT download
            srt_res = self.client.get(f"/api/v1/jobs/{job_id}/srt")
            self.assertEqual(srt_res.status_code, 200)
            self.assertIn("Dòng thứ nhất kịch bản.", srt_res.text)
            self.assertIn("-->", srt_res.text)

    def test_batch_endpoint_rejects_empty_lines(self):
        response = self.client.post("/api/v1/tts/batch", json={"lines": []})
        self.assertEqual(response.status_code, 422)

    def test_multilingual_tts_endpoint_success(self):
        with patch("services.job_manager.execute_model_inference", return_value=(torch.zeros(1, 2400), 24000)):
            response = self.client.post(
                "/api/v1/tts/multilingual",
                data={
                    "text": "Hello world, testing multilingual synthesis.",
                    "language_id": "en",
                    "exaggeration": 0.6,
                    "temperature": 0.85,
                },
            )
            self.assertEqual(response.status_code, 202)
            job_id = response.json()["id"]
            completed = self.wait_for_job(job_id, timeout=6)
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(completed["params"]["language_id"], "en")
            self.assertEqual(completed["params"]["exaggeration"], 0.6)

    def test_multilingual_tts_endpoint_normalizes_language_code(self):
        with patch("services.job_manager.execute_model_inference", return_value=(torch.zeros(1, 2400), 24000)):
            response = self.client.post(
                "/api/v1/tts/multilingual",
                data={
                    "text": "Bonjour tout le monde.",
                    "language_id": " FR ",
                },
            )
            self.assertEqual(response.status_code, 202)
            job_id = response.json()["id"]
            completed = self.wait_for_job(job_id, timeout=6)
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(completed["params"]["language_id"], "fr")

    def test_multilingual_tts_endpoint_rejects_unsupported_language(self):
        response = self.client.post(
            "/api/v1/tts/multilingual",
            data={
                "text": "Xin chào thế giới.",
                "language_id": "vi",
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("Ngôn ngữ không được hỗ trợ", response.json()["detail"])

    def test_multilingual_tts_endpoint_rejects_empty_text(self):
        response = self.client.post(
            "/api/v1/tts/multilingual",
            data={
                "text": "   ",
                "language_id": "en",
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_models_list_endpoint(self):
        response = self.client.get("/api/v1/models")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("models", data)
        model_names = [m["name"] for m in data["models"]]
        self.assertIn("nano", model_names)
        self.assertIn("turbo", model_names)
        self.assertIn("standard", model_names)
        self.assertIn("multilingual", model_names)

    def test_model_preload_and_unload_endpoints(self):
        with patch("services.inference.load_model", return_value=(None, 24000)):
            # 1. Preload nano model
            res_load = self.client.post("/api/v1/models/nano/load")
            self.assertEqual(res_load.status_code, 200)
            self.assertEqual(res_load.json()["status"], "ok")
            self.assertEqual(res_load.json()["model"], "nano")

            # 2. Check health reports loaded_model
            res_health = self.client.get("/api/v1/health")
            self.assertEqual(res_health.json()["loaded_model"], "nano")

            # 3. Unload nano model
            res_unload = self.client.delete("/api/v1/models/nano")
            self.assertEqual(res_unload.status_code, 200)
            self.assertEqual(res_unload.json()["status"], "ok")

            # 4. Check health reports None
            res_health2 = self.client.get("/api/v1/health")
            self.assertIsNone(res_health2.json()["loaded_model"])

    def test_model_preload_rejects_invalid_name(self):
        res = self.client.post("/api/v1/models/hacker_bot/load")
        self.assertEqual(res.status_code, 422)

    def test_model_preload_rejects_uncached_offline_model(self):
        with patch("routers.system.is_multilingual_cached", return_value=False):
            res = self.client.post("/api/v1/models/multilingual/load")
            self.assertEqual(res.status_code, 404)
            self.assertIn("Mô hình Multilingual chưa được tải về máy", res.json()["detail"])

    def test_delete_model_from_disk_endpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_models = Path(temp_dir) / "models"
            temp_nano = temp_models / "models--ResembleAI--chatterbox-nano"
            temp_nano.mkdir(parents=True, exist_ok=True)
            (temp_nano / "fake_weight.pt").write_bytes(b"0" * 1024)

            with patch("api_app.PROJECT_DIR", Path(temp_dir)):
                res = self.client.delete("/api/v1/models/nano/disk")
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json()["status"], "ok")
                self.assertFalse(temp_nano.exists())

    def test_delete_model_from_disk_rejects_invalid_name(self):
        res = self.client.delete("/api/v1/models/invalid_ai/disk")
        self.assertEqual(res.status_code, 422)


if __name__ == "__main__":
    unittest.main()



