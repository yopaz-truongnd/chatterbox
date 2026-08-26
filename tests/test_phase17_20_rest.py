"""Integration tests for all Phase 17-20 REST endpoints."""

import os
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient

import api_app
from services.voice_project_service import VoiceProjectService
from services.voice_project_store import VoiceProjectStore
from services.tts.fake import FakeTTSProvider


class TestPhase17to20REST(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ["CHATTERBOX_API_DATA_DIR"] = str(self.tmp.name)
        os.environ["CHATTERBOX_IN_PROCESS"] = "1"

        self.client = TestClient(api_app.app)
        self.store = VoiceProjectStore(root_dir=Path(self.tmp.name) / "projects")
        self.provider = FakeTTSProvider()
        self.proj_service = VoiceProjectService(
            store=self.store, execution_port=self.provider, provider_name="fake"
        )

    def tearDown(self):
        self.tmp.cleanup()

    # ---------------- Phase 17: Runtime ----------------
    def test_get_runtime_capabilities_endpoint(self):
        res = self.client.get("/api/v1/voice-runtime/capabilities")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("available", data)
        self.assertIn("supported_output_formats", data)

    def test_run_preflight_endpoint(self):
        pid = "rest_preflight_proj"
        self.proj_service.create_project("The dawn broke over the mountains.", project_id=pid)
        res = self.client.post(
            f"/api/v1/voice-runtime/preflight/{pid}",
            json={"provider": "fake", "requested_formats": ["wav"]},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["project_id"], pid)
        self.assertTrue(data["passed"])

    # ---------------- Phase 18: Assets ----------------
    def test_voice_assets_endpoints(self):
        # 1. List assets (empty initially)
        res = self.client.get("/api/v1/voice-assets")
        self.assertEqual(res.status_code, 200)

        # 2. Match assets
        res_match = self.client.post(
            "/api/v1/voice-assets/match",
            json={"intents": ["thunder"], "category": "sfx"},
        )
        self.assertEqual(res_match.status_code, 200)
        self.assertIsInstance(res_match.json(), list)

    # ---------------- Phase 19: Series ----------------
    def test_voice_series_crud_and_episodes_endpoints(self):
        # 1. Create series
        create_payload = {
            "title": "REST Mythology Saga",
            "description": "A tale of ancient gods",
            "language": "en",
            "voice_bible": {"narrator_character": "sage", "provider": "fake"},
        }
        res = self.client.post("/api/v1/voice-series", json=create_payload)
        self.assertEqual(res.status_code, 201)
        series_data = res.json()
        sid = series_data["series_id"]

        # 2. Get series
        res_get = self.client.get(f"/api/v1/voice-series/{sid}")
        self.assertEqual(res_get.status_code, 200)
        self.assertEqual(res_get.json()["title"], "REST Mythology Saga")

        # 3. Add episode
        self.proj_service.create_project("Chapter 1 script", project_id="proj_rest_ep1")
        ep_res = self.client.post(
            f"/api/v1/voice-series/{sid}/episodes",
            json={"project_id": "proj_rest_ep1", "title": "Chapter 1", "episode_number": 1},
        )
        self.assertEqual(ep_res.status_code, 201)

        # 4. List episodes
        res_eps = self.client.get(f"/api/v1/voice-series/{sid}/episodes")
        self.assertEqual(res_eps.status_code, 200)
        self.assertEqual(len(res_eps.json()), 1)

    # ---------------- Phase 20: Health & Events ----------------
    def test_health_and_events_endpoints(self):
        pid = "proj_rest_health"
        self.proj_service.create_project("Short text", project_id=pid)

        # Health
        res_h = self.client.get(f"/api/v1/voice-projects/{pid}/health")
        self.assertEqual(res_h.status_code, 200)
        self.assertEqual(res_h.json()["project_id"], pid)

        # Events
        res_e = self.client.get(f"/api/v1/voice-projects/{pid}/events")
        self.assertEqual(res_e.status_code, 200)
        self.assertIsInstance(res_e.json(), list)

        # Diagnostics
        res_d = self.client.post(f"/api/v1/voice-projects/{pid}/diagnostics")
        self.assertEqual(res_d.status_code, 200)
        self.assertIn("health", res_d.json())
