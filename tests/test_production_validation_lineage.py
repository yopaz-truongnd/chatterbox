"""Unit tests for Phase 21 production lineage and incremental reproduction validation."""

from pathlib import Path
import tempfile
import unittest

from services.production_validation_models import ProductionValidationRequest
from services.production_validation_service import ProductionValidationService
from services.tts.fake import FakeTTSProvider
from services.voice_project_models import compute_file_sha256
from services.voice_project_store import VoiceProjectStore
from services.voice_project_service import VoiceProjectService
from services.voice_project_models import MixPlanStaleError


class TestProductionValidationLineage(unittest.TestCase):
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

    def test_lineage_verification_and_incremental_reproduction(self):
        script = (
            "The storm raged across Mount Olympus with furious thunder.\n\n"
            "Prometheus held the smoldering spark against the bitter cold.\n\n"
            "Mortals looked up from the shadows as the dawn approached."
        )
        req = ProductionValidationRequest(
            script_text=script,
            provider="fake",
            model="nano",
            output_formats=["wav"],
            require_final_approval=True,
            require_narration_acceptance=True,
            run_incremental_reproduction=True,
        )

        report = self.service.validate(req)
        self.assertEqual(report.status, "completed")
        self.assertTrue(report.incremental_reproduction_passed)

        # Verify artifacts and lineage
        self.assertGreater(len(report.artifacts), 0)
        final_wav_art = next((a for a in report.artifacts if a.file_name == "FINAL.wav"), None)
        self.assertIsNotNone(final_wav_art)
        self.assertTrue(final_wav_art.verified_lineage)

        # Confirm physical file exists and SHA256 matches
        proj_dir = self.store.get_project_dir(report.project_id)
        final_wav_path = proj_dir / "exports" / "FINAL.wav"
        self.assertTrue(final_wav_path.exists())
        self.assertEqual(compute_file_sha256(final_wav_path), final_wav_art.sha256)

        # The canonical verifier must reject upstream selected-attempt tampering,
        # even when the export manifest and final file still match each other.
        manifest = self.store.load_manifest(report.project_id)
        beat = next(iter(manifest.beats.values()))
        selected = next(a for a in beat.attempts if a.attempt == beat.selected_attempt)
        selected_path = proj_dir / selected.audio_path
        selected_path.write_bytes(selected_path.read_bytes() + b"tampered")
        with self.assertRaises(MixPlanStaleError):
            VoiceProjectService(store=self.store, execution_port=self.provider).verify_delivery_lineage(
                report.project_id
            )


if __name__ == "__main__":
    unittest.main()
