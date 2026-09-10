"""Tests for LocalRuntimeService capabilities inspection (Phase 17)."""

import unittest
from unittest import mock

from services.local_runtime_models import LocalRuntimeCapabilities
from services.local_runtime_service import LocalRuntimeService


class TestLocalRuntimeCapabilities(unittest.TestCase):
    def setUp(self):
        self.service = LocalRuntimeService()

    def test_capabilities_returns_typed_model(self):
        caps = self.service.get_capabilities()
        self.assertIsInstance(caps, LocalRuntimeCapabilities)
        self.assertIsInstance(caps.available, bool)
        self.assertIsInstance(caps.supported_output_formats, list)
        self.assertIn("wav", caps.supported_output_formats)

    def test_capabilities_when_job_manager_none(self):
        with mock.patch("services.local_runtime_service._get_job_manager", return_value=None):
            caps = self.service.get_capabilities()
            self.assertFalse(caps.available)
            self.assertTrue(any("JobManager is not running" in w for w in caps.warnings))

    def test_capabilities_when_job_manager_present(self):
        fake_jm = mock.MagicMock()
        fake_jm.max_workers = 3
        with mock.patch("services.local_runtime_service._get_job_manager", return_value=fake_jm):
            caps = self.service.get_capabilities()
            self.assertTrue(caps.available)
            self.assertEqual(caps.max_concurrent_jobs, 3)

    def test_no_http_requests_made(self):
        # Guarantee no HTTP requests or socket connections are initiated
        with mock.patch("urllib.request.urlopen") as mock_url, mock.patch("http.client.HTTPConnection") as mock_conn:
            self.service.get_capabilities()
            mock_url.assert_not_called()
            mock_conn.assert_not_called()
