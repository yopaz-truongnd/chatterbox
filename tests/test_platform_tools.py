import unittest
from unittest.mock import patch

from utils.platform_tools import primary_shortcut, select_device


class SelectDeviceTestCase(unittest.TestCase):
    @patch("utils.platform_tools.sys.platform", "darwin")
    def test_macos_uses_command_shortcuts(self):
        self.assertEqual(primary_shortcut(), ("Command", "⌘"))

    @patch("utils.platform_tools.sys.platform", "linux")
    def test_other_platforms_use_control_shortcuts(self):
        self.assertEqual(primary_shortcut(), ("Control", "Ctrl"))

    @patch("utils.platform_tools.torch.backends.mps.is_available", return_value=True)
    @patch("utils.platform_tools.torch.cuda.is_available", return_value=False)
    def test_auto_prefers_mps_when_cuda_is_unavailable(self, _cuda, _mps):
        self.assertEqual(select_device(), "mps")

    @patch("utils.platform_tools.torch.backends.mps.is_available", return_value=True)
    @patch("utils.platform_tools.torch.cuda.is_available", return_value=True)
    def test_cpu_preference_is_respected(self, _cuda, _mps):
        self.assertEqual(select_device("cpu"), "cpu")

    @patch("utils.platform_tools.torch.backends.mps.is_available", return_value=False)
    @patch("utils.platform_tools.torch.cuda.is_available", return_value=False)
    def test_unavailable_accelerator_falls_back_to_cpu(self, _cuda, _mps):
        self.assertEqual(select_device("mps"), "cpu")


if __name__ == "__main__":
    unittest.main()
