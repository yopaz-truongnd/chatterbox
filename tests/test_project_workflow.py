"""Unit and Integration Tests for Project Planning, Requirements Gathering & Lifecycle Confirmation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api_app import app
from services import project_planner
from services.exceptions import (
    ProjectNotApprovedError,
    ProjectNotFoundError,
    ProjectStateError,
    ValidationError,
)


class ProjectWorkflowTestCase(unittest.TestCase):
    """Test suite for the two-stage confirmation audio project planning workflow."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir_patch = patch.dict("os.environ", {"CHATTERBOX_API_DATA_DIR": self.temp_dir.name})
        self.data_dir_patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.data_dir_patch.stop()
        self.temp_dir.cleanup()

    def test_text_heuristic_extraction(self):
        sample_prompt = "Tạo podcast 5 phút bằng tiếng Việt về AI cho người mới, giọng kể nhẹ nhàng, nhạc nền nhẹ, xuất wav và srt"
        reqs = project_planner.extract_requirements_from_text(sample_prompt)

        self.assertEqual(reqs.get("content_format"), "podcast")
        self.assertEqual(reqs.get("target_duration_seconds"), 300)
        self.assertEqual(reqs.get("language"), "vi")
        self.assertEqual(reqs.get("audience"), "beginner")
        self.assertEqual(reqs.get("tone"), "gentle storytelling")
        self.assertEqual(reqs.get("sfx_level"), "light")
        self.assertIn("wav", reqs.get("output_formats", []))
        self.assertIn("srt", reqs.get("output_formats", []))

    def test_prepare_project_missing_required_returns_single_batch_questions(self):
        # Only topic provided, missing format, duration, audience
        res = project_planner.prepare_project(topic="Lịch sử Trí tuệ Nhân tạo")
        self.assertEqual(res["status"], "awaiting_answers")
        self.assertIn("proj_", res["project_id"])
        self.assertTrue(len(res["questions"]) >= 3)
        question_ids = {q["id"] for q in res["questions"]}
        self.assertIn("content_format", question_ids)
        self.assertIn("target_duration", question_ids)
        self.assertIn("audience", question_ids)

    def test_prepare_project_with_auto_defaults(self):
        # Format, duration, audience provided with auto_defaults=True
        initial = {
            "content_format": "podcast",
            "target_duration_seconds": 300,
            "audience": "beginner",
        }
        res = project_planner.prepare_project(
            topic="Lịch sử AI",
            initial_requirements=initial,
            auto_defaults=True,
        )
        self.assertEqual(res["status"], "awaiting_confirmation")
        self.assertEqual(len(res["questions"]), 0)
        self.assertIn("Tóm tắt cấu hình", res["summary"])
        self.assertIn("Xác nhận cấu hình", res["summary"])

    def test_full_two_stage_confirmation_lifecycle(self):
        # 1. Prepare: user enters raw topic
        prep = project_planner.prepare_project(topic="Khám phá Vũ trụ")
        proj_id = prep["project_id"]
        self.assertEqual(prep["status"], "awaiting_answers")

        # 2. Answer: user answers all missing required questions in one go
        answers = {
            "content_format": "video_narration",
            "target_duration": "3 phút",
            "audience": "đại chúng",
            "sfx_level": "cinematic",
        }
        ans_res = project_planner.answer_project_questions(
            project_id=proj_id,
            answers=answers,
            auto_defaults=True,
        )
        self.assertEqual(ans_res["status"], "awaiting_confirmation")
        self.assertIn("video_narration", ans_res["requirements"]["content_format"])
        self.assertEqual(ans_res["requirements"]["target_duration_seconds"], 180)
        self.assertEqual(ans_res["requirements"]["sfx_level"], "cinematic")

        # 3. Render BEFORE confirmation -> MUST BE REJECTED with ProjectNotApprovedError
        with self.assertRaises(ProjectNotApprovedError) as ctx:
            project_planner.render_project(project_id=proj_id)
        self.assertIn("chưa được phê duyệt", str(ctx.exception))

        # 4. Explicit Confirmation -> Transitions to approved
        conf_res = project_planner.confirm_project(project_id=proj_id, confirmed=True)
        self.assertEqual(conf_res["status"], "approved")

        # 5. Render AFTER confirmation -> Succeeds and returns job_id
        render_res = project_planner.render_project(project_id=proj_id, script_text="Kịch bản khám phá vũ trụ chi tiết.")
        self.assertEqual(render_res["status"], "rendering")
        self.assertIsNotNone(render_res["job_id"])
        self.assertIn("Kịch bản khám phá vũ trụ", render_res["script_text"])

    def test_rejection_and_cancellation(self):
        prep = project_planner.prepare_project(topic="Sách nói Triết học", auto_defaults=True)
        proj_id = prep["project_id"]

        cancel_res = project_planner.confirm_project(project_id=proj_id, confirmed=False)
        self.assertEqual(cancel_res["status"], "cancelled")

        with self.assertRaises(ProjectNotApprovedError):
            project_planner.render_project(project_id=proj_id)

    def test_fastapi_rest_endpoints(self):
        # Test prepare endpoint with full required attributes
        resp1 = self.client.post("/api/v1/projects/prepare", json={"topic": "Podcast AI 5 phút cho người mới", "auto_defaults": True})
        self.assertEqual(resp1.status_code, 201)
        data1 = resp1.json()
        proj_id = data1["project_id"]

        # Test render endpoint on unapproved project (Should fail 400)
        resp_unapproved = self.client.post(f"/api/v1/projects/{proj_id}/render", json={})
        self.assertEqual(resp_unapproved.status_code, 400)
        self.assertIn("chưa được phê duyệt", resp_unapproved.json()["detail"])

        # Test confirm endpoint
        resp_confirm = self.client.post(f"/api/v1/projects/{proj_id}/confirm", json={"confirmed": True})
        self.assertEqual(resp_confirm.status_code, 200)
        self.assertEqual(resp_confirm.json()["status"], "approved")

        # Test render endpoint after approval (Should succeed 200)
        resp_render = self.client.post(f"/api/v1/projects/{proj_id}/render", json={"script_text": "Script test"})
        self.assertEqual(resp_render.status_code, 200)
        self.assertEqual(resp_render.json()["status"], "rendering")


if __name__ == "__main__":
    unittest.main()
