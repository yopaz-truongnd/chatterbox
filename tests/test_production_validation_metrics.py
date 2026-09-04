"""Unit tests for Phase 21 Production Validation metrics and sanitization."""

from pathlib import Path
import tempfile
import unittest

from services.production_validation_models import ProductionValidationRequest
from services.production_validation_service import (
    ProductionValidationService,
    _get_machine_summary,
    _get_peak_memory_mb,
    _sanitize_path,
)
from services.tts.fake import FakeTTSProvider
from services.voice_project_store import VoiceProjectStore


class TestProductionValidationMetrics(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = VoiceProjectStore(Path(self.tmp.name) / "projects")
        self.provider = FakeTTSProvider()
        self.service = ProductionValidationService(
            store=self.store,
            execution_port=self.provider,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_machine_summary_and_peak_memory(self):
        summary = _get_machine_summary()
        self.assertIn("os", summary)
        self.assertIn("python_version", summary)
        self.assertIn("cpu_count", summary)

        mem = _get_peak_memory_mb()
        self.assertIsInstance(mem, float)
        self.assertGreater(mem, 0.0)

    def test_path_sanitization_does_not_leak_absolute_user_paths(self):
        abs_p = Path("/Users/username/secret_workspace/projects/vproj_123/mix/master.wav")
        sanitized = _sanitize_path(abs_p)
        self.assertNotIn("/Users/username/secret_workspace", sanitized)
        self.assertEqual(sanitized, "projects/vproj_123/mix/master.wav")

    def test_metrics_collection_and_no_full_script_in_report(self):
        script = (
            "Zeus looked upon the mortals with cold indifference.\n\n"
            "Prometheus rose to bring them hope and golden warmth."
        )
        req = ProductionValidationRequest(
            script_text=script,
            provider="fake",
            model="nano",
            output_formats=["wav"],
            run_incremental_reproduction=False,
        )
        report = self.service.validate(req)

        # Confirm metrics were populated
        self.assertGreater(report.total_duration_ms, 0.0)
        self.assertEqual(report.beat_count, 2)
        self.assertEqual(len(report.per_beat_metrics), 2)
        for bm in report.per_beat_metrics:
            self.assertGreater(bm.text_length, 0)
            self.assertEqual(bm.provider, "fake")

        # Confirm no full script stored directly in report fields
        report_dict = report.model_dump(mode="json")
        self.assertNotIn("script_text", report_dict)
        self.assertNotIn(script, str(report_dict))


if __name__ == "__main__":
    unittest.main()
