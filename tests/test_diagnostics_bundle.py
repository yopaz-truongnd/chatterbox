"""Unit tests for Diagnostics Bundle generation & sanitization (Phase 20)."""

from pathlib import Path
import tempfile
import unittest

from services.diagnostics_service import DiagnosticsService
from services.production_event_models import ProductionEvent, ProductionEventType
from services.production_event_store import ProductionEventStore
from services.voice_project_service import VoiceProjectService
from services.voice_project_store import VoiceProjectStore
from services.voice_series_service import VoiceSeriesService
from services.voice_series_store import VoiceSeriesStore
from services.tts.fake import FakeTTSProvider


class TestDiagnosticsBundle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.proj_store = VoiceProjectStore(root_dir=Path(self.tmp.name) / "projects")
        self.series_store = VoiceSeriesStore(root_dir=Path(self.tmp.name) / "series")
        self.event_store = ProductionEventStore(root_dir=Path(self.tmp.name) / "projects")
        self.provider = FakeTTSProvider()
        self.proj_service = VoiceProjectService(
            store=self.proj_store, execution_port=self.provider, provider_name="fake"
        )
        self.series_service = VoiceSeriesService(store=self.series_store)
        self.diag_service = DiagnosticsService(
            project_store=self.proj_store,
            series_store=self.series_store,
            event_store=self.event_store,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_project_diagnostics_sanitized_of_secrets_and_absolute_paths(self):
        pid = "proj_diag_01"
        self.proj_service.create_project("The whispering wind told of forgotten realms.", project_id=pid)
        self.event_store.append_project_event(
            ProductionEvent(
                project_id=pid,
                event_type=ProductionEventType.WORKFLOW_STARTED,
                message="Workflow starting with key secret_token_12345",
            )
        )

        bundle = self.diag_service.create_project_diagnostics(pid)

        self.assertEqual(bundle["project_id"], pid)
        self.assertIn("health", bundle)
        self.assertIn("runtime_capabilities", bundle)
        self.assertIn("recent_events", bundle)

        bundle_str = str(bundle)
        # Verify no private absolute paths like /Users/... leaked
        self.assertNotIn(str(self.proj_store.root_dir), bundle_str)

    def test_series_diagnostics_bundle(self):
        series = self.series_service.create_series(title="Mythological Saga")
        bundle = self.diag_service.create_series_diagnostics(series.series_id)

        self.assertEqual(bundle["series_id"], series.series_id)
        self.assertIn("health", bundle)
        self.assertIn("series_state", bundle)
