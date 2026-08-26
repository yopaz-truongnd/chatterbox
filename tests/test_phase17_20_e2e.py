"""End-to-End Production integration smoke test across Phases 17-20."""

import os
from pathlib import Path
import tempfile
import unittest
import wave

from services.asset_library_models import AssetCategory
from services.asset_library_service import AssetLibraryService
from services.asset_library_store import AssetLibraryStore
from services.local_runtime_service import LocalRuntimeService
from services.production_event_models import ProductionEvent, ProductionEventType
from services.production_event_store import ProductionEventStore
from services.production_health_service import get_project_health, get_series_health
from services.voice_project_service import VoiceProjectService
from services.voice_project_store import VoiceProjectStore
from services.voice_project_workflow import VoiceProjectWorkflowService
from services.voice_project_workflow_store import VoiceProjectWorkflowStore
from services.voice_series_models import (
    SeriesPronunciationBible,
    SeriesSoundBible,
    SeriesVoiceBible,
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


class TestPhase17to20E2E(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        os.environ["CHATTERBOX_API_DATA_DIR"] = str(self.root)
        os.environ["CHATTERBOX_IN_PROCESS"] = "1"

        self.proj_store = VoiceProjectStore(root_dir=self.root / "projects")
        self.series_store = VoiceSeriesStore(root_dir=self.root / "series")
        self.event_store = ProductionEventStore(root_dir=self.root / "projects")
        self.wf_store = VoiceProjectWorkflowStore(root_dir=self.root / "workflows")

        self.assets_root = self.root / "assets"
        self.assets_root.mkdir(parents=True, exist_ok=True)
        self.asset_store = AssetLibraryStore(index_path=self.assets_root / "library-index.yaml")
        self.asset_service = AssetLibraryService(
            store=self.asset_store, permitted_roots=[self.assets_root]
        )

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
        self.series_service = VoiceSeriesService(store=self.series_store)
        self.series_ops = VoiceSeriesOperations(
            service=self.series_service,
            store=self.series_store,
            proj_store=self.proj_store,
            proj_service=self.proj_service,
            wf_service=self.wf_service,
        )
        self.runtime_service = LocalRuntimeService()

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_production_pipeline_e2e(self):
        # 1. Inspect runtime capabilities
        caps = self.runtime_service.get_capabilities()
        self.assertIsInstance(caps.supported_output_formats, list)

        # 2. Ingest SFX asset into library
        thunder_wav = self.assets_root / "thunder.wav"
        _make_dummy_wav(thunder_wav)
        ingest_res = self.asset_service.ingest_file(
            thunder_wav,
            category=AssetCategory.SFX,
            metadata={"intents": ["thunder_strike"], "mood": "dramatic"},
        )
        self.assertEqual(ingest_res.status, "registered")

        # 3. Create Series with Bibles
        series = self.series_service.create_series(
            title="Saga of the Storm Gods",
            description="Mythological audio drama of tempestuous deities.",
            voice_bible=SeriesVoiceBible(narrator_character="elder_sage", provider="fake"),
            pronunciation_bible=SeriesPronunciationBible(overrides={"Zhulong": "dzh-oo-long"}),
            sound_bible=SeriesSoundBible(mastering_profile="storytelling", output_formats=["wav"]),
        )

        # 4. Create and add 2 Episode Projects
        ep1_pid = "proj_storm_ep1"
        ep2_pid = "proj_storm_ep2"

        self.proj_service.create_project("The skies darkened over the ancient mountaintop.", project_id=ep1_pid)
        self.proj_service.create_project("A bolt of lightning struck the iron tree.", project_id=ep2_pid)

        ep1 = self.series_service.add_episode(series.series_id, ep1_pid, "The Darkening", 1)
        ep2 = self.series_service.add_episode(series.series_id, ep2_pid, "The Iron Tree", 2)

        # 5. Run Preflight on episode 1
        issues = self.runtime_service.run_production_preflight(ep1_pid, provider="fake")
        errors = [i for i in issues if i.severity == "error"]
        self.assertEqual(len(errors), 0)

        # 6. Produce Series Batch
        exp_dir = self.root / "exports"
        summary = self.series_ops.produce_series(series.series_id, export_root=exp_dir)

        self.assertEqual(summary.total_episodes, 2)
        self.assertEqual(summary.completed, 2)
        self.assertEqual(summary.progress_percent, 100.0)

        # 7. Check Deliverable Structure
        slug = series.slug
        self.assertTrue((exp_dir / slug / "series-manifest.yaml").exists())
        self.assertTrue((exp_dir / slug / "voice-bible.yaml").exists())
        self.assertTrue((exp_dir / slug / "episode-001" / "FINAL.wav").exists())
        self.assertTrue((exp_dir / slug / "episode-002" / "FINAL.wav").exists())

        # 8. Record and query production event
        self.event_store.append_project_event(
            ProductionEvent(
                project_id=ep1_pid,
                event_type=ProductionEventType.EXPORT_COMPLETED,
                message="Episode 1 production export completed successfully.",
            )
        )
        events = self.event_store.load_project_events(ep1_pid)
        self.assertTrue(any(e["event_type"] == "export_completed" for e in events))

        # 9. Verify Health Aggregates
        proj_health = get_project_health(ep1_pid, project_store=self.proj_store)
        self.assertEqual(proj_health.project_id, ep1_pid)

        series_health = get_series_health(series.series_id, series_store=self.series_store)
        self.assertEqual(series_health.episode_count, 2)
        self.assertEqual(series_health.completed_count, 2)
