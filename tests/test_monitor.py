import importlib.util
import pathlib
import tempfile
from unittest import mock
import unittest


MODULE_PATH = pathlib.Path(__file__).parents[1] / "src" / "kwin_ctm_monitor.py"
SPEC = importlib.util.spec_from_file_location("kwin_ctm_monitor", MODULE_PATH)
monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitor)


class VersionTests(unittest.TestCase):
    def test_extracts_neon_upstream_version(self):
        self.assertEqual(
            monitor.upstream_version("4:6.7.0-0zneon+24.04+noble+release+build101"),
            "6.7.0",
        )

    def test_rejects_unknown_version(self):
        with self.assertRaises(monitor.MonitorError):
            monitor.upstream_version("unexpected")


class VkmsTests(unittest.TestCase):
    def test_finds_only_faux_driver_character_device(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            drm = root / "sys"
            dev = root / "dev"
            drivers = root / "drivers"
            devices = root / "devices"
            (drivers / "faux_driver").mkdir(parents=True)
            (drivers / "amdgpu").mkdir()
            dev.mkdir()
            for name, driver in (("card0", "faux_driver"), ("card1", "amdgpu")):
                device = devices / ("vkms" if name == "card0" else "pci-gpu")
                device.mkdir(parents=True)
                (device / "driver").symlink_to(drivers / driver)
                card = drm / name
                card.mkdir(parents=True)
                (card / "device").symlink_to(device)
            (dev / "card0").touch()
            (dev / "card1").touch()
            with mock.patch.object(pathlib.Path, "is_char_device", return_value=True):
                self.assertEqual(monitor.find_vkms_node(drm, dev), dev / "card0")

    def test_fails_closed_without_vkms(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / "sys").mkdir()
            (root / "dev").mkdir()
            with self.assertRaises(monitor.MonitorError):
                monitor.find_vkms_node(root / "sys", root / "dev")


if __name__ == "__main__":
    unittest.main()
