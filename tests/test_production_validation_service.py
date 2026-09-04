"""Unit and integration tests for ProductionValidationService."""

from pathlib import Path
import tempfile
import unittest

from services.production_validation_models import (
    ProductionValidationRequest,
    ValidationVerdict,
)
from services.production_validation_service import ProductionValidationService
from services.tts.fake import FakeTTSProvider
from services.voice_project_store import VoiceProjectStore
from services.voice_project_operations import VoiceProjectOperationManager


class TestProductionValidationService(unittest.TestCase):
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

    def test_full_production_validation_flow_with_fake_tts(self):
        script = (
            "High atop Mount Olympus, the eternal wind howled across the stone.\n\n"
            "Prometheus knelt beside the forge of Hephaestus, watching the flame.\n\n"
            "He touched the stalk... and a golden ember ignited.\n\n"
            "The Titan turned toward the mortal world, ready to defy Zeus."
        )
        req = ProductionValidationRequest(
            script_text=script,
            provider="fake",
            model="test_model",
            language="en",
            output_formats=["wav"],
            require_final_approval=True,
            require_narration_acceptance=True,
            run_incremental_reproduction=True,
        )

        report = self.service.validate(req)

        self.assertEqual(report.status, "completed")
        self.assertIn(report.verdict, (ValidationVerdict.PASS, ValidationVerdict.PASS_WITH_WARNINGS))
        self.assertGreater(report.beat_count, 0)
        self.assertGreater(len(report.steps), 5)
        self.assertGreater(len(report.per_beat_metrics), 0)
        self.assertGreater(len(report.artifacts), 0)

        # Check step names
        step_names = [s.name for s in report.steps]
        self.assertIn("create_project", step_names)
        self.assertIn("plan_voice_project", step_names)
        self.assertIn("render_narration", step_names)
        self.assertIn("mix_audio", step_names)
        self.assertIn("master_audio", step_names)
        self.assertIn("export_deliverables", step_names)
        self.assertIn("audio_and_lineage_validation", step_names)

        # Verify on-disk persistence
        retrieved = self.service.get_validation_report(report.validation_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.validation_id, report.validation_id)

    def test_validation_profile_loading(self):
        profile = self.service.load_validation_profile()
        self.assertIsInstance(profile, dict)
        self.assertEqual(profile.get("provider"), "local")
        self.assertEqual(profile.get("language"), "en")

    def test_async_submit_uses_same_validation_id_and_operation(self):
        manager = VoiceProjectOperationManager(
            max_workers=1, operations_dir=Path(self.tmp.name) / "operations"
        )
        service = ProductionValidationService(
            store=self.store, execution_port=self.provider, operation_manager=manager
        )
        report, operation = service.submit(ProductionValidationRequest(
            script_text="Prometheus carried the flame.", provider="fake",
            output_formats=["wav"], run_incremental_reproduction=False,
        ))
        self.assertEqual(report.operation_ids, [operation.id])
        self.assertEqual(service.get_validation_report(report.validation_id).validation_id, report.validation_id)

    def test_network_service_rejects_raw_paths(self):
        with self.assertRaisesRegex(ValueError, "local CLI"):
            self.service.validate(ProductionValidationRequest(
                script_path="/etc/passwd", provider="fake", output_formats=["wav"]
            ))

    def test_managed_profile_rejects_traversal(self):
        with self.assertRaisesRegex(ValueError, "managed profile ID"):
            self.service.load_validation_profile("../secret.yaml")


if __name__ == "__main__":
    unittest.main()
