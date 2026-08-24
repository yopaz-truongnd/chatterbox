"""REST contract tests for autonomous voice workflows."""

from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient

import api_app
from services.voice_project_workflow_models import (
    VoiceWorkflowState,
    WorkflowPolicy,
    WorkflowStatus,
    WorkflowStep,
)


class TestVoiceWorkflowsAPI(TestCase):
    def test_create_preserves_policy_and_step_operation_progress(self):
        policy = WorkflowPolicy(
            provider="fake",
            retry_budget=4,
            allow_resource_substitute=False,
            mixing_profile="dramatic",
            require_final_approval=True,
        )
        state = VoiceWorkflowState(
            workflow_id="vwf_rest_policy",
            project_id="rest_policy",
            status=WorkflowStatus.WAITING_FOR_HUMAN,
            policy=policy,
            steps=[
                WorkflowStep(
                    name="master",
                    status="completed",
                    operation_id="vp_op_123",
                    progress_percent=100.0,
                )
            ],
            human_action={"action_type": "final_audio_approval"},
        )

        with patch("routers.voice_workflows.get_voice_project_workflow_service") as get_service:
            get_service.return_value.start_workflow.return_value = state
            with TestClient(api_app.app) as client:
                response = client.post(
                    "/api/v1/voice-workflows",
                    json={
                        "project_id": "rest_policy",
                        "script_text": "A quiet valley.",
                        "policy": policy.model_dump(mode="json"),
                    },
                )

        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["status"], "waiting_for_human")
        self.assertFalse(body["policy"]["allow_resource_substitute"])
        self.assertEqual(body["policy"]["mixing_profile"], "dramatic")
        self.assertTrue(body["policy"]["require_final_approval"])
        self.assertEqual(body["steps"][0]["operation_id"], "vp_op_123")
        self.assertEqual(body["steps"][0]["progress_percent"], 100.0)

        forwarded = get_service.return_value.start_workflow.call_args.kwargs["policy"]
        self.assertEqual(forwarded, policy)

    def test_repeated_get_does_not_recover_running_workflow(self):
        state = VoiceWorkflowState(
            workflow_id="vwf_running_poll",
            project_id="running_poll",
            status=WorkflowStatus.RUNNING,
        )
        with patch("routers.voice_workflows.get_voice_project_workflow_service") as get_service:
            get_service.return_value.get_workflow.return_value = state
            with TestClient(api_app.app) as client:
                responses = [client.get("/api/v1/voice-workflows/vwf_running_poll") for _ in range(3)]

        self.assertTrue(all(response.status_code == 200 for response in responses))
        self.assertTrue(all(response.json()["status"] == "running" for response in responses))


if __name__ == "__main__":
    import unittest

    unittest.main()
