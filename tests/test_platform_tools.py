import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from utils.platform_tools import (
    check_ffmpeg_available,
    detect_full_diagnostics,
    detect_system_profile,
    get_default_data_dir,
    is_port_available,
    primary_shortcut,
    select_device,
)


class SelectDeviceTestCase(unittest.TestCase):
    @patch("utils.platform_tools.sys.platform", "darwin")
    def test_macos_uses_command_shortcuts(self):
        self.assertEqual(primary_shortcut(), ("Command", "⌘"))

    @patch("utils.platform_tools.sys.platform", "win32")
    def test_windows_uses_control_shortcuts(self):
        self.assertEqual(primary_shortcut(), ("Control", "Ctrl"))

    @patch("utils.platform_tools.sys.platform", "linux")
    def test_linux_uses_control_shortcuts(self):
        self.assertEqual(primary_shortcut(), ("Control", "Ctrl"))

    @patch("utils.platform_tools.sys.platform", "darwin")
    @patch("utils.platform_tools.torch.backends.mps.is_available", return_value=True)
    @patch("utils.platform_tools.torch.cuda.is_available", return_value=False)
    def test_macos_auto_prefers_mps(self, _cuda, _mps):
        self.assertEqual(select_device("auto"), "mps")

    @patch("utils.platform_tools.sys.platform", "win32")
    @patch("utils.platform_tools.torch.cuda.is_available", return_value=True)
    def test_windows_auto_prefers_cuda(self, _cuda):
        self.assertEqual(select_device("auto"), "cuda")

    @patch("utils.platform_tools.sys.platform", "win32")
    @patch("utils.platform_tools.torch.cuda.is_available", return_value=False)
    def test_windows_auto_falls_back_to_cpu(self, _cuda):
        self.assertEqual(select_device("auto"), "cpu")

    @patch("utils.platform_tools.torch.backends.mps.is_available", return_value=True)
    @patch("utils.platform_tools.torch.cuda.is_available", return_value=True)
    def test_cpu_preference_is_respected(self, _cuda, _mps):
        self.assertEqual(select_device("cpu"), "cpu")

    @patch("utils.platform_tools.torch.backends.mps.is_available", return_value=False)
    @patch("utils.platform_tools.torch.cuda.is_available", return_value=False)
    def test_unavailable_accelerator_falls_back_to_cpu(self, _cuda, _mps):
        self.assertEqual(select_device("mps"), "cpu")

    @patch("utils.platform_tools.sys.platform", "win32")
    def test_windows_default_data_dir(self):
        env_copy = os.environ.copy()
        env_copy.pop("CHATTERBOX_API_DATA_DIR", None)
        env_copy.pop("CHATTERBOX_DATA_DIR", None)
        env_copy["LOCALAPPDATA"] = "C:\\Users\\Test\\AppData\\Local"
        with patch.dict(os.environ, env_copy, clear=True):
            data_dir = get_default_data_dir()
            self.assertIn("Chatterbox", str(data_dir))
            self.assertTrue(str(data_dir).endswith("data"))

    @patch("utils.platform_tools.sys.platform", "darwin")
    def test_macos_default_data_dir(self):
        env_copy = os.environ.copy()
        env_copy.pop("CHATTERBOX_API_DATA_DIR", None)
        env_copy.pop("CHATTERBOX_DATA_DIR", None)
        with patch.dict(os.environ, env_copy, clear=True):
            data_dir = get_default_data_dir()
            self.assertIn("Application Support", str(data_dir))
            self.assertIn("Chatterbox", str(data_dir))

    def test_port_availability_check(self):
        import socket
        # 1. Bind to ephemeral port 0 to obtain an actively used port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            occupied_port = s.getsockname()[1]
            # While socket is open, is_port_available should return False
            self.assertFalse(is_port_available("127.0.0.1", occupied_port))

        # 2. Once socket is closed, port should be available again
        self.assertTrue(is_port_available("127.0.0.1", occupied_port))

    def test_ffmpeg_check_returns_tuple(self):
        available, hint = check_ffmpeg_available()
        self.assertIsInstance(available, bool)
        if not available:
            self.assertIsNotNone(hint)

    def test_full_diagnostics_structure(self):
        diag = detect_full_diagnostics("auto")
        self.assertIn("os", diag)
        self.assertIn("platform", diag)
        self.assertIn("torch", diag)
        self.assertIn("device", diag)
        self.assertIn("ram_total_gb", diag)
        self.assertIn("recommended_model", diag)
        self.assertIn("data_dir", diag)
        self.assertIn("checkpoints", diag)
        self.assertIn("warnings", diag)


if __name__ == "__main__":
    unittest.main()
