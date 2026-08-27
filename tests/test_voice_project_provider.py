"""Unit tests for Server TTS Provider Resolution and Wiring (Phase 12-13 Hardening)."""

import unittest
from unittest.mock import MagicMock, patch

from services.tts.chatterbox_job import ChatterboxJobProvider
from services.tts.fake import FakeTTSProvider
from services.tts.gemini import GeminiTTSProvider
from services.voice_project_dependencies import resolve_server_tts_provider
from services.voice_renderer import ProviderUnavailableError


class TestVoiceProjectProviderWiring(unittest.TestCase):
    """Verify strict provider resolution without silent HTTP or fake fallbacks."""

    def test_local_provider_without_jobmanager_raises_provider_unavailable(self):
        with patch("api_app.job_manager", None):
            with self.assertRaises(ProviderUnavailableError) as ctx:
                resolve_server_tts_provider("local")
            self.assertIn("JobManager", str(ctx.exception))

    def test_local_provider_with_jobmanager_returns_chatterbox_job_provider(self):
        mock_jm = MagicMock()
        with patch("api_app.job_manager", mock_jm):
            provider = resolve_server_tts_provider("local", model="turbo")
            self.assertIsInstance(provider, ChatterboxJobProvider)
            self.assertEqual(provider.default_model, "turbo")

    def test_fake_provider_explicitly_resolves_fake(self):
        provider = resolve_server_tts_provider("fake")
        self.assertIsInstance(provider, FakeTTSProvider)

    def test_gemini_provider_resolves_gemini(self):
        provider = resolve_server_tts_provider("gemini", model="gemini-2.5-flash", voice="Puck")
        self.assertIsInstance(provider, GeminiTTSProvider)
        self.assertEqual(provider.model_name, "gemini-2.5-flash")

    def test_unsupported_provider_raises_error(self):
        with self.assertRaises(ProviderUnavailableError):
            resolve_server_tts_provider("non_existent_provider_xyz")


if __name__ == "__main__":
    unittest.main()
