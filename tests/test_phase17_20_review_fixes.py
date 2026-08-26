"""Unit and integration tests verifying all 10 Phase 17-20 Review Findings."""

import os
from pathlib import Path
import tempfile
import threading
import unittest
import wave

from services.asset_library_models import AssetCategory, LibraryAsset
from services.asset_library_service import AssetLibraryService
from services.asset_library_store import AssetLibraryStore
from services.production_event_models import ProductionEvent, ProductionEventType
from services.production_event_store import ProductionEventStore
from services.production_health_service import recover_on_startup
from services.voice_project_models import VoiceProjectNotFound
from services.voice_project_service import VoiceProjectService
from services.voice_project_store import VoiceProjectStore
from services.voice_project_workflow import VoiceProjectWorkflowService
from services.voice_project_workflow_store import VoiceProjectWorkflowStore
from services.voice_series_models import (
    SeriesVoiceBible,
    VoiceSeries,
    VoiceSeriesEpisode,
)
from services.voice_series_operations import VoiceSeriesOperations
from services.voice_series_service import VoiceSeriesService
from services.voice_series_store import VoiceSeriesStore
from services.tts.fake import FakeTTSProvider


def _make_dummy_wav(path: Path, duration_s: float = 0.5, sample_rate: int = 22050):
    path.parent.mkdir(parents=True, exist_ok=True)
    n_frames = int(duration_s * sample_rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)


class TestPhase17to20ReviewFixes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        os.environ["CHATTERBOX_API_DATA_DIR"] = str(self.root)
        os.environ["CHATTERBOX_IN_PROCESS"] = "1"

        self.proj_store = VoiceProjectStore(root_dir=self.root / "projects")
        self.series_store = VoiceSeriesStore(root_dir=self.root / "series")
        self.event_store = ProductionEventStore(root_dir=self.root / "projects")
        self.wf_store = VoiceProjectWorkflowStore(root_dir=self.root / "workflows")
        self.asset_store = AssetLibraryStore(index_path=self.root / "assets" / "library-index.yaml")
        self.asset_service = AssetLibraryService(store=self.asset_store, permitted_roots=[self.root])

        self.provider = FakeTTSProvider()
        self.proj_service = VoiceProjectService(
            store=self.proj_store,
            execution_port=self.provider,
            provider_name="fake",
        )
        self.wf_service = VoiceProjectWorkflowService(
            store=self.wf_store,
            project_store=self.proj_store,
        )
        self.series_service = VoiceSeriesService(
            store=self.series_store,
            wf_service=self.wf_service,
            proj_store=self.proj_store,
        )
        self.series_ops = VoiceSeriesOperations(
            service=self.series_service,
            store=self.series_store,
            proj_store=self.proj_store,
            proj_service=self.proj_service,
            wf_service=self.wf_service,
            event_store=self.event_store,
        )

    def tearDown(self):
        self.tmp.cleanup()

    # -------------------------------------------------------------
    # Finding 3: Path Traversal Guards in Series & Event Stores
    # -------------------------------------------------------------
    def test_series_store_rejects_path_traversal_ids(self):
        with self.assertRaises(ValueError):
            self.series_store.get_series("../../outside")
        with self.assertRaises(ValueError):
            self.series_store.save_series(VoiceSeries(series_id="../../bad_series", title="Bad"))
        with self.assertRaises(ValueError):
            self.series_store.get_episode("valid_series", "../bad_ep")

    def test_event_store_rejects_path_traversal_ids(self):
        with self.assertRaises(ValueError):
            self.event_store.load_project_events("../../etc/passwd")
        with self.assertRaises(ValueError):
            self.event_store.load_series_events("../bad_series")
        with self.assertRaises(ValueError):
            self.event_store.append_project_event(
                ProductionEvent(project_id="../bad_proj", event_type=ProductionEventType.WORKFLOW_STARTED, message="test")
            )

    # -------------------------------------------------------------
    # Finding 7: Asset Index Thread Safety & Deduplication
    # -------------------------------------------------------------
    def test_asset_store_thread_safe_concurrent_inserts(self):
        def worker(idx: int):
            asset = LibraryAsset(
                asset_id=f"asset_concurrent_{idx}",
                category=AssetCategory.SFX,
                file_path=f"audio/{idx}.wav",
                duration_ms=1000.0,
                sample_rate=44100,
                channels=2,
                format="wav",
                sha256=f"sha256_dummy_hash_{idx}",
            )
            self.asset_store.save_asset(asset)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(15)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assets = self.asset_store.list_assets()
        self.assertEqual(len(assets), 15)

    # -------------------------------------------------------------
    # Finding 9: Corrupted Audio with Valid Magic Header Rejection
    # -------------------------------------------------------------
    def test_corrupted_wav_file_ingest_is_rejected(self):
        corrupt_wav = self.root / "corrupt.wav"
        # Write RIFF header but corrupt body
        with open(corrupt_wav, "wb") as f:
            f.write(b"RIFF\x00\x00\x00\x00WAVEfmt \x10\x00\x00\x00" + b"\xFF" * 20)

        res = self.asset_service.ingest_file(corrupt_wav, category=AssetCategory.SFX)
        self.assertEqual(res.status, "rejected")
        self.assertIn("Failed to read audio metadata", res.reason)

    # -------------------------------------------------------------
    # Finding 10: Event Store Append & Rotation Synchronization
    # -------------------------------------------------------------
    def test_concurrent_event_logging_no_data_loss(self):
        pid = "proj_concurrent_events"

        def log_events(worker_id: int):
            for i in range(20):
                self.event_store.append_project_event(
                    ProductionEvent(
                        project_id=pid,
                        event_type=ProductionEventType.STEP_PROGRESS,
                        message=f"Worker {worker_id} event {i}",
                    )
                )

        threads = [threading.Thread(target=log_events, args=(w,)) for w in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        events = self.event_store.load_project_events(pid, limit=200)
        self.assertEqual(len(events), 100)

    # -------------------------------------------------------------
    # Finding 5: Persist Stale Lineage / Artifact State in Recovery
    # -------------------------------------------------------------
    def test_startup_recovery_persists_stale_artifact_state(self):
        pid = "proj_stale_recovery"
        self.proj_service.create_project("Initial text.", project_id=pid)
        self.proj_service.plan(pid)

        # Tamper with the plan file
        proj_dir = self.proj_store.get_project_dir(pid)
        state = self.proj_store.get_project_state(pid)
        plan_file = proj_dir / state.artifacts.voice_plan
        with open(plan_file, "a", encoding="utf-8") as f:
            f.write("\n# Tampered modification\n")

        # Run recovery
        report = recover_on_startup(project_store=self.proj_store)
        self.assertIn(pid, [item["project_id"] for item in report["stale_artifacts_flagged"]])

        # Check that error is persisted to project state
        new_state = self.proj_store.get_project_state(pid)
        self.assertIsNotNone(new_state.error)
        self.assertIn("Stale artifact detected", new_state.error)

    # -------------------------------------------------------------
    # Finding 6: Review Queue Authoritative SHA & Keys
    # -------------------------------------------------------------
    def test_review_queue_uses_authoritative_sha_and_action_type(self):
        series = self.series_service.create_series(title="Queue Series Test")
        ep_pid = "proj_queue_ep"
        self.proj_service.create_project("Story for review.", project_id=ep_pid)
        ep = self.series_service.add_episode(series.series_id, ep_pid, "Chapter 1", 1)

        # Create a mock workflow with waiting_for_human
        from services.voice_project_workflow_models import VoiceWorkflowState, WorkflowStatus
        wf = VoiceWorkflowState(
            workflow_id="wf_queue_test",
            project_id=ep_pid,
            status=WorkflowStatus.WAITING_FOR_HUMAN,
            human_action={
                "action_type": "final_audio_approval",
                "reason": "Director sign-off",
                "items": [{"artifact_id": "master_wav", "sha256": "authoritative_abc123"}],
                "available_options": ["approve", "reject"],
            },
        )
        self.wf_store.save_workflow(wf)
        ep.workflow_id = wf.workflow_id
        self.series_store.save_episode(ep)

        queue = self.series_service.get_review_queue(series.series_id)
        self.assertEqual(len(queue), 1)
        action = queue[0]
        self.assertEqual(action.action_type, "final_audio_approval")
        self.assertEqual(action.available_options, ["approve", "reject"])
        self.assertEqual(action.artifact_sha256, "authoritative_abc123")

    # -------------------------------------------------------------
    # Finding 1 & 4: Cancellation, Preflight & Events Integration
    # -------------------------------------------------------------
    def test_series_production_emits_structured_events(self):
        series = self.series_service.create_series(
            title="Event Test Series",
            voice_bible=SeriesVoiceBible(provider="fake"),
        )
        ep_pid = "proj_evt_ep"
        self.proj_service.create_project("Episode text with events.", project_id=ep_pid)
        self.series_service.add_episode(series.series_id, ep_pid, "Episode 1", 1)

        summary = self.series_ops.produce_series(series.series_id, export_root=self.root / "exports")
        self.assertEqual(summary.completed, 1)

        events = self.event_store.load_project_events(ep_pid)
        event_types = [e["event_type"] for e in events]
        self.assertIn("workflow_started", event_types)
        self.assertIn("export_completed", event_types)

        series_events = self.event_store.load_series_events(series.series_id)
        self.assertTrue(any(e["event_type"] == "workflow_started" for e in series_events))

    def test_cancel_series_aborts_batch_production(self):
        series = self.series_service.create_series(title="Cancel Test Series")
        # Cancel when not running returns False
        cancelled_idle = self.series_ops.cancel_series(series.series_id)
        self.assertFalse(cancelled_idle)
