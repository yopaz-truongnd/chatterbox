import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import torch
from fastapi.testclient import TestClient

import api_app
from job_store import JobStore


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
        cls.temp_dir = tempfile.TemporaryDirectory()
        api_app.API_DATA_DIR = Path(cls.temp_dir.name)
        api_app.job_store = JobStore(api_app.API_DATA_DIR / "jobs.db")
        cls.client_context = TestClient(api_app.app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        cls.temp_dir.cleanup()

    def setUp(self):
        api_app.job_queue.join()
        with api_app.jobs_lock:
            api_app.jobs.clear()
        for model_name in api_app.models:
            api_app.models[model_name] = None
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
        with patch.object(api_app, "load_model", return_value=FakeModel()):
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
        with patch.object(api_app, "load_model", return_value=FakeModel()):
            response = self.client.post("/api/v1/tts", data={"text": "Job to be cancelled."})
            self.assertEqual(response.status_code, 202)
            job_id = response.json()["id"]

            cancel_res = self.client.post(f"/api/v1/jobs/{job_id}/cancel")
            self.assertEqual(cancel_res.status_code, 200)
            self.assertEqual(cancel_res.json()["status"], "cancelled")

    def test_long_text_batch_synthesis(self):
        with patch.object(api_app, "load_model", return_value=FakeModel()):
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
        with patch.object(api_app, "load_model", return_value=FakeModel()):
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
        with patch.object(api_app, "load_model", return_value=FailingModel()):
            response = self.client.post("/api/v1/tts", data={"text": "This job fails."})
            self.assertEqual(response.status_code, 202)
            failed = self.wait_for_job(response.json()["id"])

        self.assertEqual(failed["status"], "failed")
        self.assertIn("inference failed", failed["error"])
        self.assertIsNone(failed["audio_url"])

    def test_loading_new_model_releases_previous_model(self):
        with patch.object(api_app.ChatterboxTurboTTS, "from_pretrained", return_value=object()):
            api_app.load_model("turbo")
            self.assertEqual(
                [name for name, model in api_app.models.items() if model is not None],
                ["turbo"],
            )

            api_app.load_model("nano")

        self.assertEqual(
            [name for name, model in api_app.models.items() if model is not None],
            ["nano"],
        )
        api_app.cleanup_runtime()
        self.assertIsNotNone(api_app.models["nano"])

    def test_completed_job_can_be_filtered_and_deleted(self):
        with patch.object(api_app, "load_model", return_value=FakeModel()):
            response = self.client.post("/api/v1/tts", data={"text": "Delete this output."})
            completed = self.wait_for_job(response.json()["id"])

        jobs = self.client.get("/api/v1/jobs", params={"status": "completed"}).json()
        self.assertGreaterEqual(jobs["count"], 1)

        deleted = self.client.delete(f"/api/v1/jobs/{completed['id']}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get(f"/api/v1/jobs/{completed['id']}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
