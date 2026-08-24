"""Comprehensive tests for FastAPI Voice Projects REST API (Phase 12-14)."""

import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

import api_app
from services.voice_project_dependencies import get_voice_project_store


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

    def test_lifecycle_full_rest_api_including_phase14(self):
        # Valid clean script with zero required missing gaps
        script_text = "The morning sun rose gently over the calm green valley."

        # 1. Create Project (201 Created)
        create_resp = self.client.post(
            "/api/v1/voice-projects",
            json={
                "project_id": "rest_valley_01",
                "title": "Morning Valley",
                "language": "en",
                "script_text": script_text,
            },
        )
        self.assertEqual(create_resp.status_code, 201, create_resp.text)
        created_data = create_resp.json()
        self.assertEqual(created_data["project_id"], "rest_valley_01")
        self.assertEqual(created_data["stage"], "NEW")

        # Duplicate create returns 409 Conflict
        dup_resp = self.client.post(
            "/api/v1/voice-projects",
            json={"project_id": "rest_valley_01", "script_text": "duplicate"},
        )
        self.assertEqual(dup_resp.status_code, 409)
        self.assertEqual(dup_resp.json()["error"]["code"], "PROJECT_ALREADY_EXISTS")

        # 2. Get Project Summary (200 OK)
        get_resp = self.client.get("/api/v1/voice-projects/rest_valley_01")
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json()["project_id"], "rest_valley_01")

        # 3. List Projects (200 OK)
        list_resp = self.client.get("/api/v1/voice-projects?limit=10")
        self.assertEqual(list_resp.status_code, 200)
        items = list_resp.json()
        self.assertTrue(any(p["project_id"] == "rest_valley_01" for p in items))

        # 4. Trigger Plan (202 Accepted)
        plan_resp = self.client.post("/api/v1/voice-projects/rest_valley_01/plan")
        self.assertEqual(plan_resp.status_code, 202)
        plan_op_id = plan_resp.json()["job_id"]
        self._wait_for_op(plan_op_id)

        # 5. Get VoicePlan (200 OK)
        plan_artifact_resp = self.client.get("/api/v1/voice-projects/rest_valley_01/plan")
        self.assertEqual(plan_artifact_resp.status_code, 200)
        plan_dict = plan_artifact_resp.json()
        self.assertIn("beats", plan_dict)
        self.assertGreater(len(plan_dict["beats"]), 0)

        # 6. Trigger Resource Check (202 Accepted)
        res_resp = self.client.post("/api/v1/voice-projects/rest_valley_01/resources/check")
        self.assertEqual(res_resp.status_code, 202)
        self._wait_for_op(res_resp.json()["job_id"])

        # 7. Get Resource Report & Missing Gaps (200 OK)
        rep_resp = self.client.get("/api/v1/voice-projects/rest_valley_01/resources")
        self.assertEqual(rep_resp.status_code, 200)
        self.assertFalse(rep_resp.json()["readiness"]["render_blocked"])

        missing_resp = self.client.get("/api/v1/voice-projects/rest_valley_01/resources/missing")
        self.assertEqual(missing_resp.status_code, 200)
        self.assertFalse(missing_resp.json()["render_blocked"])

        # 8. Trigger Render (202 Accepted) with provider=fake (Strict: no allow_blocked parameter)
        render_resp = self.client.post(
            "/api/v1/voice-projects/rest_valley_01/render",
            json={"provider": "fake"},
        )
        self.assertEqual(render_resp.status_code, 202)
        self._wait_for_op(render_resp.json()["job_id"])

        # Verify Project state after render
        final_summary_resp = self.client.get("/api/v1/voice-projects/rest_valley_01")
        self.assertEqual(final_summary_resp.status_code, 200)
        summary_data = final_summary_resp.json()
        self.assertEqual(summary_data["stage"], "NARRATION_READY")
        self.assertEqual(summary_data["beats"]["passed"], summary_data["beats"]["total"])

        # 9. Trigger Selective Single Beat Render (202 Accepted)
        first_beat_id = plan_dict["beats"][0]["id"]
        beat_render_resp = self.client.post(
            f"/api/v1/voice-projects/rest_valley_01/beats/{first_beat_id}/render",
            json={"provider": "fake"},
        )
        self.assertEqual(beat_render_resp.status_code, 202)
        self._wait_for_op(beat_render_resp.json()["job_id"])

        # 10. Trigger QC Re-evaluation (202 Accepted)
        eval_resp = self.client.post(
            "/api/v1/voice-projects/rest_valley_01/evaluate",
            json={"beats": [first_beat_id]},
        )
        self.assertEqual(eval_resp.status_code, 202)
        self._wait_for_op(eval_resp.json()["job_id"])

        # 11. Phase 14: Prepare Mix (202 Accepted)
        prep_resp = self.client.post(
            "/api/v1/voice-projects/rest_valley_01/mix/prepare",
            json={"mastering_profile": "storytelling", "output_formats": ["wav"]},
        )
        self.assertEqual(prep_resp.status_code, 202)
        self._wait_for_op(prep_resp.json()["job_id"])

        # Get MixPlan
        mix_plan_resp = self.client.get("/api/v1/voice-projects/rest_valley_01/mix-plan")
        self.assertEqual(mix_plan_resp.status_code, 200)
        self.assertIn("voice_clips", mix_plan_resp.json())

        # 12. Phase 14: Execute Mix (202 Accepted)
        mix_resp = self.client.post("/api/v1/voice-projects/rest_valley_01/mix")
        self.assertEqual(mix_resp.status_code, 202)
        self._wait_for_op(mix_resp.json()["job_id"])

        # 13. Phase 14: Execute Master (202 Accepted)
        master_resp = self.client.post("/api/v1/voice-projects/rest_valley_01/master")
        self.assertEqual(master_resp.status_code, 202)
        self._wait_for_op(master_resp.json()["job_id"])

        # 14. Phase 14: Execute Export (202 Accepted)
        export_resp = self.client.post("/api/v1/voice-projects/rest_valley_01/export")
        self.assertEqual(export_resp.status_code, 202)
        self._wait_for_op(export_resp.json()["job_id"])

        # Verify artifacts list
        art_resp = self.client.get("/api/v1/voice-projects/rest_valley_01/artifacts")
        self.assertEqual(art_resp.status_code, 200)
        artifacts = art_resp.json()["artifacts"]
        self.assertTrue(any(a["id"] == "final_wav" for a in artifacts))

        # Download FINAL.wav
        down_resp = self.client.get("/api/v1/voice-projects/rest_valley_01/artifacts/final_wav")
        self.assertEqual(down_resp.status_code, 200)
        self.assertEqual(down_resp.headers["content-type"], "audio/wav")
        self.assertGreater(len(down_resp.content), 0)

    def test_strict_resource_blocked_gate_fails_before_enqueue(self):
        # Script with unknown proper noun requiring pronunciation
        script_text = "Long ago the mysterious beast Qiongqi roamed Mount Zhong."
        self.client.post(
            "/api/v1/voice-projects",
            json={"project_id": "blocked_gate_proj", "script_text": script_text},
        )
        plan_resp = self.client.post("/api/v1/voice-projects/blocked_gate_proj/plan")
        self._wait_for_op(plan_resp.json()["job_id"])

        res_resp = self.client.post("/api/v1/voice-projects/blocked_gate_proj/resources/check")
        self._wait_for_op(res_resp.json()["job_id"])

        # Attempting to render without resolving required pronunciation MUST fail immediately with 409
        render_resp = self.client.post(
            "/api/v1/voice-projects/blocked_gate_proj/render",
            json={"provider": "fake"},
        )
        self.assertEqual(render_resp.status_code, 409)
        self.assertEqual(render_resp.json()["error"]["code"], "RESOURCE_BLOCKED")

    def test_update_script_invalidates_downstream_and_enforces_replan(self):
        self.client.post(
            "/api/v1/voice-projects",
            json={"project_id": "stale_script_proj", "script_text": "Original text"},
        )
        plan_resp = self.client.post("/api/v1/voice-projects/stale_script_proj/plan")
        self._wait_for_op(plan_resp.json()["job_id"])

        put_resp = self.client.put(
            "/api/v1/voice-projects/stale_script_proj/script",
            json={"script_text": "Modified new text"},
        )
        self.assertEqual(put_resp.status_code, 200)
        self.assertEqual(put_resp.json()["stage"], "NEW")

        # Attempting to render immediately must return 409 STALE_ARTIFACT
        render_resp = self.client.post(
            "/api/v1/voice-projects/stale_script_proj/render",
            json={"provider": "fake"},
        )
        self.assertEqual(render_resp.status_code, 409)
        self.assertEqual(render_resp.json()["error"]["code"], "STALE_ARTIFACT")

    def test_nonexistent_project_returns_404(self):
        resp = self.client.get("/api/v1/voice-projects/nonexistent_xyz")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error"]["code"], "PROJECT_NOT_FOUND")

    def test_cancel_operation_job(self):
        self.client.post(
            "/api/v1/voice-projects",
            json={"project_id": "cancel_proj_rest", "script_text": "Text for cancellation test"},
        )
        plan_resp = self.client.post("/api/v1/voice-projects/cancel_proj_rest/plan")
        job_id = plan_resp.json()["job_id"]

        cancel_resp = self.client.post(f"/api/v1/voice-project-jobs/{job_id}/cancel")
        self.assertIn(cancel_resp.status_code, (200, 400))

    def test_mix_plan_stale_detection(self):
        script = "The morning sun rose gently over the calm green valley."
        self.client.post("/api/v1/voice-projects", json={"project_id": "stale_mix_proj", "script_text": script})
        p_res = self.client.post("/api/v1/voice-projects/stale_mix_proj/plan")
        self._wait_for_op(p_res.json()["job_id"])

        c_res = self.client.post("/api/v1/voice-projects/stale_mix_proj/resources/check")
        self._wait_for_op(c_res.json()["job_id"])

        r_res = self.client.post("/api/v1/voice-projects/stale_mix_proj/render", json={"provider": "fake"})
        self._wait_for_op(r_res.json()["job_id"])

        prep_res = self.client.post("/api/v1/voice-projects/stale_mix_proj/mix/prepare")
        self._wait_for_op(prep_res.json()["job_id"])

        # Mutate an underlying audio render attempt file
        store = get_voice_project_store()
        proj_dir = store.get_project_dir("stale_mix_proj")
        manifest = store.load_manifest("stale_mix_proj")
        first_beat = next(iter(manifest.beats.values()))
        audio_file = proj_dir / first_beat.attempts[0].audio_path
        if audio_file.exists():
            with open(audio_file, "ab") as f:
                f.write(b"\x00\x00\x00\x00")  # Corrupt hash

        # Mix must fail with 409 MIX_PLAN_STALE
        mix_res = self.client.post("/api/v1/voice-projects/stale_mix_proj/mix")
        job_id = mix_res.json()["job_id"]
        op_data = self._wait_for_op(job_id)
        self.assertEqual(op_data["status"], "failed")
        self.assertIn("stale", op_data["error"]["message"].lower())

    def _wait_for_op(self, job_id: str, max_retries: int = 50):
        for _ in range(max_retries):
            resp = self.client.get(f"/api/v1/voice-project-jobs/{job_id}")
            if resp.status_code == 200:
                data = resp.json()
                if data["status"] in ("completed", "failed", "cancelled", "interrupted"):
                    return data
            time.sleep(0.05)
        self.fail(f"Operation {job_id} did not finish in time.")


if __name__ == "__main__":
    unittest.main()
