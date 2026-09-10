"""Focused authoritative next-action tests for Phase 24."""

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from services.director_review_models import (
    DirectorArtifactStatus,
    DirectorProjectReview,
    DirectorRevisionEvent,
)
from services.director_revision_store import DirectorRevisionStore
from services.voice_project_operations import (
    OperationStatus,
    VoiceProjectOperation,
    VoiceProjectOperationManager,
)
from services.voice_project_store import VoiceProjectStore
from services.voice_project_workflow import VoiceProjectWorkflowService
from services.voice_project_workflow_models import VoiceWorkflowState, WorkflowPolicy, WorkflowStatus
from services.voice_project_workflow_store import VoiceProjectWorkflowStore


class TestVoiceOrchestrationPhase24(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name)
        self.project_store = VoiceProjectStore(root / "projects")
        self.workflow_store = VoiceProjectWorkflowStore(root / "workflows")
        self.operations = VoiceProjectOperationManager(operations_dir=root / "operations")
        self.service = VoiceProjectWorkflowService(
            store=self.workflow_store,
            project_store=self.project_store,
            op_manager=self.operations,
        )

    def tearDown(self):
        self.operations._executor.shutdown(wait=False)
        self.tmp.cleanup()

    def _save(self, status, human_action=None, project_id="phase24", **kwargs):
        state = VoiceWorkflowState(
            workflow_id=f"wf_{project_id}",
            project_id=project_id,
            status=status,
            human_action=human_action,
            **kwargs,
        )
        self.workflow_store.save_workflow(state)
        return state

    def test_active_operation_is_monitored_without_duplicate_submission(self):
        state = self._save(WorkflowStatus.RUNNING)
        operation = VoiceProjectOperation(
            id="vp_op_active", project_id=state.project_id, operation="render", status=OperationStatus.RUNNING
        )
        self.operations._operations[operation.id] = operation

        decision = self.service.next_action(state.workflow_id)

        self.assertEqual(decision.next_action, "monitor_operation")
        self.assertEqual(decision.operation_id, operation.id)
        self.assertFalse(decision.requires_human)

    def test_human_boundaries_stop_autonomous_progression(self):
        cases = {
            "resource_required": ("request_resources", "required_resources"),
            "narration_acceptance": ("request_narration_approval", "narration_acceptance"),
            "final_audio_approval": ("request_final_audio_approval", "final_audio_approval"),
            "audio_quality_review": ("request_qc_direction", "retry_budget_exhausted"),
        }
        for index, (gate, expected) in enumerate(cases.items()):
            state = self._save(
                WorkflowStatus.WAITING_FOR_HUMAN,
                project_id=f"gate_{index}",
                human_action={"action_type": gate, "items": [{"sha256": "current"}]},
            )
            decision = self.service.next_action(state.workflow_id)
            self.assertTrue(decision.requires_human)
            self.assertEqual((decision.next_action, decision.blocking_issue), expected)
            self.assertEqual(decision.parameters["items"], [{"sha256": "current"}])

    def test_interrupted_and_pending_revision_recovery_use_persisted_state(self):
        interrupted = self._save(WorkflowStatus.INTERRUPTED, project_id="interrupted")
        self.assertEqual(self.service.next_action(interrupted.workflow_id).next_action, "resume_workflow")
        with mock.patch("services.voice_project_workflow.threading.Thread.start"):
            resumed = self.service.resume_workflow(interrupted.workflow_id)
        self.assertEqual(resumed.status, WorkflowStatus.RUNNING)

        pending = self._save(WorkflowStatus.COMPLETED, project_id="timing_pending")
        self.project_store.get_project_dir(pending.project_id).mkdir(parents=True)
        DirectorRevisionStore(self.project_store).append(DirectorRevisionEvent(
            revision_id="rev_timing",
            project_id=pending.project_id,
            beat_id="B01",
            affected_beats=["B01"],
            revision_type="timing",
            required_reproduction_steps=["prepare_mix", "mix", "master", "export"],
        ))

        decision = self.service.next_action(pending.workflow_id)
        self.assertEqual(decision.next_action, "reproduce_pending_revisions")
        self.assertNotIn("render_beat", decision.parameters["required_reproduction_steps"])

    def test_stale_artifact_is_never_presented_as_deliverable(self):
        state = self._save(
            WorkflowStatus.COMPLETED,
            project_id="stale_delivery",
            policy=WorkflowPolicy(output_formats=["wav"]),
        )
        review = mock.Mock(spec=DirectorProjectReview)
        review.artifact_status = [
            DirectorArtifactStatus(artifact_id="final_wav", exists=True, fresh=False, sha256="stale")
        ]
        with mock.patch(
            "services.director_review_service.DirectorReviewService.get_review",
            return_value=review,
        ):
            decision = self.service.next_action(state.workflow_id)

        self.assertEqual(decision.next_action, "request_recovery_direction")
        self.assertEqual(decision.blocking_issue, "stale_or_unverified_artifact")
        self.assertTrue(decision.requires_human)


if __name__ == "__main__":
    unittest.main()
