"""Unit tests for Voice Project Preflight Request Validation."""

from pathlib import Path
import tempfile
import unittest

from services.render_models import ProjectStatus
from services.voice_project_models import (
    BeatNotFoundError,
    InvalidProjectStateError,
    ResourceBlockedError,
    VoiceProjectNotFound,
)
from services.voice_project_preflight import VoiceProjectPreflight
from services.voice_project_service import VoiceProjectService
from services.voice_project_store import VoiceProjectStore


class TestVoiceProjectPreflight(unittest.TestCase):
    """Test synchronous preflight request validation."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = VoiceProjectStore(root_dir=Path(self.temp_dir.name) / "projects")
        self.preflight = VoiceProjectPreflight(store=self.store)
        self.service = VoiceProjectService(store=self.store, provider_name="fake")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_preflight_nonexistent_project_fails(self):
        with self.assertRaises(VoiceProjectNotFound):
            self.preflight.validate_plan_request("missing_proj")

    def test_preflight_resource_check_fails_if_unplanned(self):
        self.service.create_project(project_id="unplanned_proj", script_text="Sample script")
        with self.assertRaises(InvalidProjectStateError):
            self.preflight.validate_resource_check_request("unplanned_proj")

    def test_preflight_render_fails_if_resource_report_blocked(self):
        # Script with unknown proper noun requiring pronunciation
        script = "Long ago the beast Qiongqi walked Mount Zhong."
        self.service.create_project(project_id="blocked_proj", script_text=script)
        self.service.plan("blocked_proj")
        self.service.check_resources("blocked_proj")

        with self.assertRaises(ResourceBlockedError):
            self.preflight.validate_render_request("blocked_proj")

    def test_preflight_beat_render_fails_on_unknown_beat(self):
        script = "The morning sun rose gently over the calm green valley."
        self.service.create_project(project_id="clean_proj", script_text=script)
        self.service.plan("clean_proj")
        self.service.check_resources("clean_proj")

        with self.assertRaises(BeatNotFoundError):
            self.preflight.validate_beat_render_request("clean_proj", "B99_UNKNOWN")


if __name__ == "__main__":
    unittest.main()
