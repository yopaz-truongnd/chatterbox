"""Comprehensive tests for FastAPI Voice Projects REST API (Phase 12)."""

import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import api_app
from services.voice_project_dependencies import (
    get_voice_project_operation_manager,
    get_voice_project_service,
    get_voice_project_store,
)
from services.voice_project_store import VoiceProjectStore


class TestVoiceProjectsAPI(unittest.TestCase):
    """Test REST endpoints for Voice Projects."""

    @classmethod
    def setUpClass(cls):
        os.environ["CHATTERBOX_IN_PROCESS"] = "1"
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.projects_root = Path(cls.temp_dir.name) / "projects"
        cls.projects_root.mkdir(parents=True, exist_ok=True)
        os.environ["CHATTERBOX_API_DATA_DIR"] = str(cls.temp_dir.name)

        cls.client_context = TestClient(api_app.app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        cls.temp_dir.cleanup()

    def test_lifecycle_full_rest_api(self):
        script_text = (
            "Long ago in ancient times, the Torch Dragon opened its eyes, "
            "and radiant daylight swept across the land."
        )

        # 1. Create Project (201 Created)
        create_resp = self.client.post(
            "/api/v1/voice-projects",
            json={
                "project_id": "rest_dragon_01",
                "title": "The Torch Dragon of Mount Zhong",
                "language": "en",
                "script_text": script_text,
            },
        )
        self.assertEqual(create_resp.status_code, 201, create_resp.text)
        created_data = create_resp.json()
        self.assertEqual(created_data["project_id"], "rest_dragon_01")
        self.assertEqual(created_data["stage"], "NEW")
        self.assertIn("plan", created_data["suggested_action"].lower())

        # Duplicate create returns 409 Conflict
        dup_resp = self.client.post(
            "/api/v1/voice-projects",
            json={
                "project_id": "rest_dragon_01",
                "script_text": "duplicate",
            },
        )
        self.assertEqual(dup_resp.status_code, 409)
        self.assertEqual(dup_resp.json()["error"]["code"], "PROJECT_ALREADY_EXISTS")

        # 2. Get Project Summary (200 OK)
        get_resp = self.client.get("/api/v1/voice-projects/rest_dragon_01")
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json()["project_id"], "rest_dragon_01")

        # 3. List Projects (200 OK)
        list_resp = self.client.get("/api/v1/voice-projects?limit=10")
        self.assertEqual(list_resp.status_code, 200)
        items = list_resp.json()
        self.assertTrue(any(p["project_id"] == "rest_dragon_01" for p in items))

        # 4. Trigger Plan (202 Accepted)
        plan_resp = self.client.post("/api/v1/voice-projects/rest_dragon_01/plan")
        self.assertEqual(plan_resp.status_code, 202)
        plan_op_id = plan_resp.json()["job_id"]
        self.assertTrue(plan_op_id.startswith("vp_op_"))

        # Poll operation job status until complete
        self._wait_for_op(plan_op_id)

        # 5. Get VoicePlan (200 OK)
        plan_artifact_resp = self.client.get("/api/v1/voice-projects/rest_dragon_01/plan")
        self.assertEqual(plan_artifact_resp.status_code, 200)
        plan_dict = plan_artifact_resp.json()
        self.assertIn("beats", plan_dict)
        self.assertGreater(len(plan_dict["beats"]), 0)

        # 6. Trigger Resource Check (202 Accepted)
        res_resp = self.client.post("/api/v1/voice-projects/rest_dragon_01/resources/check")
        self.assertEqual(res_resp.status_code, 202)
        res_op_id = res_resp.json()["job_id"]
        self._wait_for_op(res_op_id)

        # 7. Get Resource Report & Missing Gaps (200 OK)
        rep_resp = self.client.get("/api/v1/voice-projects/rest_dragon_01/resources")
        self.assertEqual(rep_resp.status_code, 200)

        missing_resp = self.client.get("/api/v1/voice-projects/rest_dragon_01/resources/missing")
        self.assertEqual(missing_resp.status_code, 200)
        self.assertIn("required", missing_resp.json())
        self.assertIn("recommended", missing_resp.json())

        # 8. Trigger Render (202 Accepted) with provider=fake for speed and test isolation
        render_resp = self.client.post(
            "/api/v1/voice-projects/rest_dragon_01/render",
            json={
                "provider": "fake",
                "allow_blocked": True,
            },
        )
        self.assertEqual(render_resp.status_code, 202)
        render_op_id = render_resp.json()["job_id"]
        self._wait_for_op(render_op_id)

        # Verify Project state after render
        final_summary_resp = self.client.get("/api/v1/voice-projects/rest_dragon_01")
        self.assertEqual(final_summary_resp.status_code, 200)
        summary_data = final_summary_resp.json()
        self.assertEqual(summary_data["stage"], "NARRATION_READY")
        self.assertEqual(summary_data["beats"]["passed"], summary_data["beats"]["total"])

        # 9. Trigger Selective Single Beat Render (202 Accepted)
        first_beat_id = plan_dict["beats"][0]["id"]
        beat_render_resp = self.client.post(
            f"/api/v1/voice-projects/rest_dragon_01/beats/{first_beat_id}/render",
            json={"provider": "fake", "allow_blocked": True},
        )
        self.assertEqual(beat_render_resp.status_code, 202)
        self._wait_for_op(beat_render_resp.json()["job_id"])

        # 10. Trigger QC Re-evaluation (202 Accepted)
        eval_resp = self.client.post(
            "/api/v1/voice-projects/rest_dragon_01/evaluate",
            json={"beats": [first_beat_id]},
        )
        self.assertEqual(eval_resp.status_code, 202)
        self._wait_for_op(eval_resp.json()["job_id"])

    def test_update_script_invalidates_downstream_and_enforces_replan(self):
        # Create project and plan it
        self.client.post(
            "/api/v1/voice-projects",
            json={"project_id": "stale_script_proj", "script_text": "Original text"},
        )
        plan_resp = self.client.post("/api/v1/voice-projects/stale_script_proj/plan")
        self._wait_for_op(plan_resp.json()["job_id"])

        # Update script via PUT
        put_resp = self.client.put(
            "/api/v1/voice-projects/stale_script_proj/script",
            json={"script_text": "Modified new text"},
        )
        self.assertEqual(put_resp.status_code, 200)
        self.assertEqual(put_resp.json()["stage"], "NEW")

        # Attempting to render immediately must return 409 STALE_ARTIFACT
        render_resp = self.client.post(
            "/api/v1/voice-projects/stale_script_proj/render",
            json={"provider": "fake", "allow_blocked": True},
        )
        self.assertEqual(render_resp.status_code, 409)
        self.assertEqual(render_resp.json()["error"]["code"], "STALE_ARTIFACT")

    def test_nonexistent_project_returns_404(self):
        resp = self.client.get("/api/v1/voice-projects/nonexistent_xyz")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error"]["code"], "PROJECT_NOT_FOUND")

    def test_cancel_operation_job(self):
        # Create project
        self.client.post(
            "/api/v1/voice-projects",
            json={"project_id": "cancel_proj_rest", "script_text": "Text for cancellation test"},
        )
        plan_resp = self.client.post("/api/v1/voice-projects/cancel_proj_rest/plan")
        job_id = plan_resp.json()["job_id"]

        cancel_resp = self.client.post(f"/api/v1/voice-project-jobs/{job_id}/cancel")
        self.assertIn(cancel_resp.status_code, (200, 400))  # 400 if already finished instantly

    def _wait_for_op(self, job_id: str, max_retries: int = 50):
        for _ in range(max_retries):
            resp = self.client.get(f"/api/v1/voice-project-jobs/{job_id}")
            if resp.status_code == 200:
                data = resp.json()
                if data["status"] in ("completed", "failed", "cancelled"):
                    return data
            time.sleep(0.05)
        self.fail(f"Operation {job_id} did not finish in time.")


if __name__ == "__main__":
    unittest.main()
