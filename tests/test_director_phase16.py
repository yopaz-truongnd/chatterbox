"""Focused Phase 16 director review, revision, and resource regressions."""

from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from services.director_review_models import BeatResourcePatch, BeatTimingPatch
from services.director_review_service import DirectorReviewService
from services.director_resource_service import DirectorResourceService
from services.director_revision_service import DirectorRevisionService
from services.director_revision_store import DirectorRevisionStore
from services.render_models import ProjectStatus, RenderStatus
from services.tts.fake import FakeTTSProvider
from services.voice_project_models import InvalidProjectStateError
from services.voice_project_service import VoiceProjectService
from services.voice_project_store import VoiceProjectStore
from services.voice_project_operations import OperationStatus, VoiceProjectOperationManager
from services.voice_project_workflow import VoiceProjectWorkflowService
from services.voice_project_workflow_models import VoiceWorkflowState, WorkflowPolicy, WorkflowStatus, WorkflowStep, WorkflowStepName
from services.voice_project_workflow_store import VoiceProjectWorkflowStore


class TestDirectorPhase16(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = VoiceProjectStore(Path(self.tmp.name) / "projects")
        self.provider = FakeTTSProvider()
        self.project_service = VoiceProjectService(
            store=self.store, execution_port=self.provider, provider_name="fake"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _rendered_project(self, project_id="director_review"):
        source = "The morning sun rose gently over the calm green valley.\n\nThen the old mountain answered with thunder."
        self.project_service.create_project(source, project_id=project_id, title="Director Review")
        self.project_service.plan(project_id)
        resources = self.project_service.check_resources(project_id)
        self.assertFalse(resources.render_blocked)
        self.project_service.render(project_id)
        return source

    def test_snapshot_preserves_exact_source_and_hides_audio_paths(self):
        source = self._rendered_project()
        review = DirectorReviewService(self.store).get_review("director_review")
        self.assertEqual("".join(source[b.source_start:b.source_end] for b in review.beats), "".join(b.source_text for b in review.beats))
        payload = review.model_dump(mode="json")
        self.assertNotIn(str(self.store.root_dir), str(payload))
        self.assertTrue(all(candidate.artifact_id for beat in review.beats for candidate in beat.available_attempts))

    def test_timing_revision_preserves_selected_attempt_and_invalidates_only_downstream(self):
        self._rendered_project("timing_revision")
        manifest = self.store.load_manifest("timing_revision")
        beat_id = next(iter(manifest.beats))
        selected = manifest.beats[beat_id].selected_attempt
        service = DirectorRevisionService(self.project_service)
        impact = service.update_timing(
            "timing_revision", beat_id, BeatTimingPatch(pause_after_ms=900), "tester"
        )
        self.assertEqual(self.store.load_manifest("timing_revision").beats[beat_id].selected_attempt, selected)
        self.assertNotIn("render_beat", impact.required_reproduction_steps)
        self.assertIn("mix_plan", impact.invalidated_artifacts)
        self.assertTrue(impact.final_approval_invalidated)

    def test_select_existing_attempt_does_not_rerender(self):
        self._rendered_project("select_attempt")
        manifest = self.store.load_manifest("select_attempt")
        beat_id = next(iter(manifest.beats))
        attempt_id = manifest.beats[beat_id].attempts[0].attempt
        service = DirectorRevisionService(self.project_service)
        with mock.patch.object(self.project_service, "render_beat") as render:
            result = service.select_attempt("select_attempt", beat_id, attempt_id, "tester")
        render.assert_not_called()
        self.assertEqual(result.selected_attempt, attempt_id)

    def test_pronunciation_resolves_gap_without_mutating_source(self):
        source = "The Zhong crossed the silent mountain at dusk."
        project_id = "pronunciation_resolution"
        self.project_service.create_project(source, project_id=project_id)
        self.project_service.plan(project_id)
        before = (self.store.get_project_dir(project_id) / "source" / "script.txt").read_bytes()
        report = self.project_service.check_resources(project_id)
        self.assertTrue(report.render_blocked)
        result = DirectorResourceService(self.project_service).add_pronunciation(
            project_id, "Zhong", "jong", "tester"
        )
        self.assertFalse(result.remaining_required_gaps)
        self.assertEqual((self.store.get_project_dir(project_id) / "source" / "script.txt").read_bytes(), before)

    def test_required_resource_cannot_be_omitted(self):
        project_id = "required_omit"
        self.project_service.create_project("The Zhong waited.", project_id=project_id)
        self.project_service.plan(project_id)
        result = self.project_service.check_resources(project_id)
        gap_id = next(g.id for g in result.report.missing if g.priority.value == "required")
        with self.assertRaises(InvalidProjectStateError):
            DirectorResourceService(self.project_service).omit_optional(project_id, gap_id, "tester")

    def test_revision_history_is_persisted_and_machine_readable(self):
        self._rendered_project("revision_history")
        manifest = self.store.load_manifest("revision_history")
        beat_id = next(iter(manifest.beats))
        DirectorRevisionService(self.project_service).update_timing(
            "revision_history", beat_id, BeatTimingPatch(pause_before_ms=100), "tester", "pace note"
        )
        revision_store = DirectorRevisionStore(self.store)
        events = revision_store.list_events("revision_history")
        self.assertEqual(events[-1].revision_type, "beat_timing_changed")
        self.assertTrue((self.store.get_project_dir("revision_history") / "revision-history.yaml").exists())

    def test_needs_review_requires_explicit_approval_and_rejected_candidate_cannot_be_selected(self):
        self._rendered_project("candidate_gate")
        manifest = self.store.load_manifest("candidate_gate")
        beat_id = next(iter(manifest.beats))
        attempt = manifest.beats[beat_id].attempts[0]
        attempt.status = RenderStatus.NEEDS_REVIEW
        manifest.beats[beat_id].status = RenderStatus.NEEDS_REVIEW
        self.store.save_manifest("candidate_gate", manifest)
        service = DirectorRevisionService(self.project_service)
        with self.assertRaises(InvalidProjectStateError):
            service.select_attempt("candidate_gate", beat_id, attempt.attempt, "tester")
        approved = service.approve_attempt("candidate_gate", beat_id, attempt.attempt, "tester")
        self.assertEqual(approved.selected_attempt, attempt.attempt)
        service.reject_attempt("candidate_gate", beat_id, attempt.attempt, "tester", "wrong delivery")
        with self.assertRaises(InvalidProjectStateError):
            service.select_attempt("candidate_gate", beat_id, attempt.attempt, "tester")

    def test_resource_path_outside_permitted_roots_is_rejected(self):
        project_id = "path_guard"
        self.project_service.create_project("The Zhong waited.", project_id=project_id)
        self.project_service.plan(project_id)
        report = self.project_service.check_resources(project_id)
        gap_id = next(g.id for g in report.report.missing if g.priority.value == "required")
        outside = Path(self.tmp.name) / "outside.wav"
        outside.write_bytes(b"RIFF")
        with self.assertRaises(ValueError):
            DirectorResourceService(self.project_service).register_asset(
                project_id, gap_id, str(outside), "knowledge", "zhong", "tester"
            )

    def test_registered_resource_survives_canonical_resource_recheck(self):
        self._rendered_project("persistent_binding")
        beat_id = next(iter(self.store.load_manifest("persistent_binding").beats))
        DirectorRevisionService(self.project_service).update_resources(
            "persistent_binding", beat_id,
            BeatResourcePatch(ambience_intent="unique_phase16_wind"), "tester",
        )
        report = self.store.load_resource_report("persistent_binding")
        gap = next(g for g in report.missing if g.intent == "unique_phase16_wind")
        asset_dir = self.store.get_project_dir("persistent_binding") / "assets"
        asset_dir.mkdir(parents=True, exist_ok=True)
        asset = asset_dir / "unique-wind.wav"
        asset.write_bytes(b"RIFF-managed-test-asset")
        DirectorResourceService(self.project_service).register_asset(
            "persistent_binding", gap.id, str(asset), "ambience", gap.intent, "tester"
        )

        rechecked = self.project_service.check_resources("persistent_binding")
        self.assertNotIn(gap.id, [item.id for item in rechecked.report.missing])

    def test_mcp_phase16_routes_to_rest_without_polling(self):
        from mcp_adapter.voice_project_tools import handle_voice_project_tool
        calls = []

        def request_fn(path, method="GET", data=None):
            calls.append((method, path, data))
            return {"project_id": "mcp_review", "status": "ok"}

        response = handle_voice_project_tool(
            "chatterbox_voice_review", {"project_id": "mcp_review"}, request_fn=request_fn
        )
        self.assertFalse(response["isError"])
        self.assertEqual(calls, [("GET", "/api/v1/voice-projects/mcp_review/director-review", None)])

    def test_rest_and_mcp_review_have_equivalent_business_payloads(self):
        import json
        from fastapi.testclient import TestClient
        import api_app
        from mcp_adapter.voice_project_tools import handle_voice_project_tool

        self._rendered_project("cross_parity")
        review_service = DirectorReviewService(self.store)
        with mock.patch("routers.voice_projects.get_director_review_service", return_value=review_service):
            with TestClient(api_app.app) as client:
                rest = client.get("/api/v1/voice-projects/cross_parity/director-review")

                def request_fn(path, method="GET", data=None):
                    return client.request(method, path, json=data).json()

                mcp = handle_voice_project_tool(
                    "chatterbox_voice_review", {"project_id": "cross_parity"}, request_fn=request_fn
                )
        self.assertEqual(rest.status_code, 200, rest.text)
        self.assertEqual(json.loads(mcp["content"][0]["text"]), rest.json())

    def test_timing_reproduction_uses_operation_manager_without_rerender(self):
        self._rendered_project("incremental_reproduction")
        beat_id = next(iter(self.store.load_manifest("incremental_reproduction").beats))
        revision = DirectorRevisionService(self.project_service)
        revision.update_timing(
            "incremental_reproduction", beat_id, BeatTimingPatch(pause_after_ms=750), "tester"
        )
        manager = VoiceProjectOperationManager(
            max_workers=1, operations_dir=Path(self.tmp.name) / "operations"
        )
        with mock.patch.object(self.project_service, "render_beat") as render:
            op = manager.submit(
                "incremental_reproduction", "reproduce", revision.reproduce_project,
                "incremental_reproduction", policy={"require_final_approval": False},
            )
            for _ in range(100):
                current = manager.get_operation(op.id)
                if current.status in {OperationStatus.COMPLETED, OperationStatus.FAILED}:
                    break
                time.sleep(0.02)
        render.assert_not_called()
        self.assertEqual(current.status, OperationStatus.COMPLETED, current.error)
        self.assertEqual(current.result["executed_steps"], ["prepare_mix", "mix", "master", "export"])

    def test_pronunciation_revision_tracks_every_affected_beat(self):
        project_id = "multi_pronunciation"
        self.project_service.create_project(
            "Zhong crossed the valley at dawn.\n\nAt dusk, Zhong returned to the mountain.",
            project_id=project_id,
        )
        self.project_service.plan(project_id)
        self.project_service.check_resources(project_id)
        result = DirectorResourceService(self.project_service).add_pronunciation(
            project_id, "Zhong", "jong", "tester"
        )
        state = DirectorRevisionStore(self.store).get_state(project_id)
        self.assertEqual(set(state.affected_beats), set(result.affected_beats))
        self.assertGreaterEqual(len(state.affected_beats), 2)

    def test_selective_reproduction_resolves_only_selected_revision(self):
        self._rendered_project("selective_revisions")
        beat_ids = list(self.store.load_manifest("selective_revisions").beats)
        service = DirectorRevisionService(self.project_service)
        first = service.update_timing("selective_revisions", beat_ids[0], BeatTimingPatch(pause_after_ms=300), "tester")
        second = service.update_timing("selective_revisions", beat_ids[-1], BeatTimingPatch(pause_after_ms=600), "tester")
        with mock.patch.object(self.project_service, "prepare_for_mix"), \
             mock.patch.object(self.project_service, "mix"), \
             mock.patch.object(self.project_service, "master"), \
             mock.patch.object(self.project_service, "export"):
            service.reproduce_project("selective_revisions", revision_ids=[first.revision_id])
        state = DirectorRevisionStore(self.store).get_state("selective_revisions")
        self.assertEqual(state.pending_revision_ids, [second.revision_id])
        self.assertEqual(state.affected_beats, [beat_ids[-1]])

    def test_resource_block_does_not_restore_narration_ready(self):
        self._rendered_project("blocked_preserve")
        state = self.store.get_project_state("blocked_preserve")
        state.stage = state.last_stable_stage = ProjectStatus.RESOURCE_BLOCKED
        self.store.save_project_state(state)
        service = DirectorRevisionService(self.project_service)
        with mock.patch.object(self.project_service, "check_resources", return_value=mock.Mock(render_blocked=True)):
            service._preserve_narration("blocked_preserve")
        self.assertEqual(self.store.get_project_state("blocked_preserve").stage.value, "RESOURCE_BLOCKED")

    def test_reproduction_preserves_authoritative_workflow_profiles(self):
        self._rendered_project("profile_reproduction")
        beat_id = next(iter(self.store.load_manifest("profile_reproduction").beats))
        revision = DirectorRevisionService(self.project_service)
        revision.update_timing("profile_reproduction", beat_id, BeatTimingPatch(pause_after_ms=420), "tester")
        workflow_store = VoiceProjectWorkflowStore(Path(self.tmp.name) / "workflows")
        workflow = VoiceWorkflowState(
            workflow_id="vwf_profiles", project_id="profile_reproduction", status=WorkflowStatus.COMPLETED,
            policy=WorkflowPolicy(mixing_profile="dramatic", mastering_profile="podcast", output_formats=["wav", "mp3"]),
        )
        workflow_store.save_workflow(workflow)
        workflow_service = VoiceProjectWorkflowService(store=workflow_store, project_store=self.store)
        with mock.patch("services.voice_project_dependencies.get_voice_project_workflow_service", return_value=workflow_service), \
             mock.patch.object(self.project_service, "prepare_for_mix") as prepare, \
             mock.patch.object(self.project_service, "mix"), \
             mock.patch.object(self.project_service, "master") as master, \
             mock.patch.object(self.project_service, "export") as export:
            revision.reproduce_project("profile_reproduction", policy={"mixing_profile": "storytelling"})
        prepare.assert_called_once_with(
            "profile_reproduction", mix_config={"profile": "dramatic"},
            mastering_profile="podcast", output_formats=["wav", "mp3"],
        )
        master.assert_called_once_with("profile_reproduction", profile_name="podcast", cancellation_token=None)
        export.assert_called_once_with("profile_reproduction", formats=["wav", "mp3"], cancellation_token=None)

    def test_completed_workflow_reopens_with_hashed_revision_approval_gate(self):
        project_id = "revision_approval"
        self.project_service.create_project("A quiet valley.", project_id=project_id)
        master = self.store.get_project_dir(project_id) / "mix" / "master.wav"
        master.parent.mkdir(parents=True, exist_ok=True)
        master.write_bytes(b"new-master")
        workflow_store = VoiceProjectWorkflowStore(Path(self.tmp.name) / "approval-workflows")
        steps = [WorkflowStep(name=name.value, status="completed") for name in WorkflowStepName]
        workflow_store.save_workflow(VoiceWorkflowState(
            workflow_id="vwf_approval", project_id=project_id, status=WorkflowStatus.COMPLETED,
            policy=WorkflowPolicy(require_final_approval=True), steps=steps,
        ))
        service = VoiceProjectWorkflowService(store=workflow_store, project_store=self.store)
        reopened = service.request_revision_approval("vwf_approval", "abc123", ["rev_one"])
        self.assertEqual(reopened.status, WorkflowStatus.WAITING_FOR_HUMAN)
        self.assertEqual(reopened.human_action["items"][0]["artifact_id"], "master_wav")
        self.assertEqual(reopened.human_action["items"][0]["sha256"], "abc123")
        self.assertEqual(reopened.human_action["revision_ids"], ["rev_one"])

    def test_client_policy_cannot_disable_workflow_final_approval(self):
        self._rendered_project("approval_policy")
        beat_id = next(iter(self.store.load_manifest("approval_policy").beats))
        revision = DirectorRevisionService(self.project_service)
        revision.update_timing("approval_policy", beat_id, BeatTimingPatch(pause_after_ms=510), "tester")
        workflow_store = VoiceProjectWorkflowStore(Path(self.tmp.name) / "policy-workflows")
        workflow_store.save_workflow(VoiceWorkflowState(
            workflow_id="vwf_policy", project_id="approval_policy", status=WorkflowStatus.COMPLETED,
            policy=WorkflowPolicy(require_final_approval=True),
        ))
        workflow_service = VoiceProjectWorkflowService(store=workflow_store, project_store=self.store)
        master_path = self.store.get_project_dir("approval_policy") / "mix" / "master.wav"
        master_path.parent.mkdir(parents=True, exist_ok=True)
        master_path.write_bytes(b"rebuilt")
        with mock.patch("services.voice_project_dependencies.get_voice_project_workflow_service", return_value=workflow_service), \
             mock.patch.object(self.project_service, "prepare_for_mix"), \
             mock.patch.object(self.project_service, "mix"), \
             mock.patch.object(self.project_service, "master"), \
             mock.patch.object(self.project_service, "export") as export, \
             mock.patch.object(workflow_service, "request_revision_approval") as gate:
            result = revision.reproduce_project("approval_policy", policy={"require_final_approval": False})
        self.assertEqual(result.status, "waiting_for_human")
        gate.assert_called_once()
        export.assert_not_called()

    def test_export_family_is_stale_after_downstream_invalidation(self):
        self._rendered_project("stale_exports")
        project_dir = self.store.get_project_dir("stale_exports")
        (project_dir / "exports").mkdir(exist_ok=True)
        (project_dir / "exports" / "FINAL.wav").write_bytes(b"old-final")
        beat_id = next(iter(self.store.load_manifest("stale_exports").beats))
        DirectorRevisionService(self.project_service).update_timing(
            "stale_exports", beat_id, BeatTimingPatch(pause_after_ms=333), "tester"
        )
        review = DirectorReviewService(self.store).get_review("stale_exports")
        final = next(item for item in review.artifact_status if item.artifact_id == "final_wav")
        self.assertTrue(final.exists)
        self.assertFalse(final.fresh)


if __name__ == "__main__":
    unittest.main()
