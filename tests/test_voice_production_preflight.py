"""Tests for Voice Production Preflight validation (Phase 17)."""

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from services.local_runtime_service import LocalRuntimeService
from services.voice_project_service import VoiceProjectService
from services.voice_project_store import VoiceProjectStore
from services.tts.fake import FakeTTSProvider


class TestVoiceProductionPreflight(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = VoiceProjectStore(Path(self.tmp.name) / "projects")
        self.provider = FakeTTSProvider()
        self.project_service = VoiceProjectService(
            store=self.store, execution_port=self.provider, provider_name="fake"
        )
        self.runtime_service = LocalRuntimeService()

    def tearDown(self):
        self.tmp.cleanup()

    def _create_project(self, project_id="preflight_proj"):
        self.project_service.create_project("A sunny morning in the realm.", project_id=project_id)
        return project_id

    def test_preflight_fails_when_project_not_found(self):
        with mock.patch("services.voice_project_dependencies.get_voice_project_store", return_value=self.store):
            issues = self.runtime_service.run_production_preflight("non_existent_proj")
            self.assertTrue(any(i.code == "PROJECT_NOT_FOUND" for i in issues))

    def test_preflight_fails_if_ffmpeg_missing_and_mp3_requested(self):
        pid = self._create_project("mp3_proj")
        with mock.patch("services.voice_project_dependencies.get_voice_project_store", return_value=self.store), \
             mock.patch("shutil.which", return_value=None):
            issues = self.runtime_service.run_production_preflight(
                pid, provider="fake", requested_formats=["mp3"]
            )
            self.assertTrue(any(i.code == "FFMPEG_MISSING" for i in issues))

    def test_preflight_passes_for_wav_when_ffmpeg_missing(self):
        pid = self._create_project("wav_proj")
        with mock.patch("services.voice_project_dependencies.get_voice_project_store", return_value=self.store), \
             mock.patch("shutil.which", return_value=None), \
             mock.patch("services.local_runtime_service.is_model_cached", return_value=True):
            issues = self.runtime_service.run_production_preflight(
                pid, provider="fake", requested_formats=["wav"]
            )
            errors = [i for i in issues if i.severity == "error"]
            self.assertEqual(len(errors), 0)

    def test_preflight_warns_on_low_disk_space(self):
        pid = self._create_project("disk_proj")
        fake_stat = mock.MagicMock(free=100 * 1024 * 1024)  # 100MB < 500MB
        with mock.patch("services.voice_project_dependencies.get_voice_project_store", return_value=self.store), \
             mock.patch("shutil.disk_usage", return_value=fake_stat), \
             mock.patch("services.local_runtime_service.is_model_cached", return_value=True):
            issues = self.runtime_service.run_production_preflight(pid, provider="fake")
            self.assertTrue(any(i.code == "LOW_DISK_SPACE" for i in issues))

    def test_server_local_provider_never_calls_localhost_http(self):
        pid = self._create_project("loopback_test")
        with mock.patch("services.voice_project_dependencies.get_voice_project_store", return_value=self.store), \
             mock.patch("urllib.request.urlopen") as mock_url, \
             mock.patch("http.client.HTTPConnection") as mock_conn:
            self.runtime_service.run_production_preflight(pid, provider="fake")
            mock_url.assert_not_called()
            mock_conn.assert_not_called()
