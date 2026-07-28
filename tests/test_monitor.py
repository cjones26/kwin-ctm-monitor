import importlib.machinery
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
    def test_local_suffix_changes_local_version(self):
        self.assertEqual(monitor.LOCAL_VERSION_SUFFIX, "local1")

    def test_madison_ignores_local_rebuild_versions(self):
        version = "4:6.7.3-0zneon+24.04+noble+release+build104"
        output = "\n".join(
            [
                f" kwin-wayland | {version}+ctm7 | file:/var/lib/kwin-ctm-monitor/repository/current stable/main amd64 Packages",
                f" kwin-wayland | {version}+local1 | file:/var/lib/kwin-ctm-monitor/repository/current stable/main amd64 Packages",
                f" kwin-wayland | {version}+local2 | file:/var/lib/kwin-ctm-monitor/repository/current stable/main amd64 Packages",
                f" kwin-wayland | {version} | http://archive.neon.kde.org/user noble/main amd64 Packages",
            ]
        )
        with mock.patch.object(monitor, "run", return_value=output):
            self.assertEqual(monitor.versions_from_madison(), [version])

    def test_already_current_status_remains_current(self):
        version = "4:6.7.0-0zneon+24.04+noble+release+build101"
        with tempfile.TemporaryDirectory() as temporary:
            status = pathlib.Path(temporary) / "status.json"
            status.write_text(
                '{"state":"published","neon_version":"%s","local_version":"%s+local1"}' % (version, version),
                encoding="utf-8",
            )
            with mock.patch.object(monitor, "STATUS", status):
                self.assertTrue(monitor.already_published(version))


class DrmDeviceTests(unittest.TestCase):
    def test_finds_primary_and_render_nodes_for_physical_gpu(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            drm = root / "sys"
            dev = root / "dev"
            drivers = root / "drivers"
            devices = root / "devices"
            (drivers / "faux_driver").mkdir(parents=True)
            (drivers / "amdgpu").mkdir()
            dev.mkdir()
            for name, driver in (("card0", "faux_driver"), ("card1", "amdgpu"), ("renderD128", "amdgpu")):
                device = devices / ("vkms" if driver == "faux_driver" else "pci-gpu")
                device.mkdir(parents=True, exist_ok=True)
                if not (device / "driver").exists():
                    (device / "driver").symlink_to(drivers / driver)
                node = drm / name
                node.mkdir(parents=True)
                (node / "device").symlink_to(device)
                (dev / name).touch()
            with mock.patch.object(pathlib.Path, "is_char_device", return_value=True):
                self.assertEqual(monitor.find_gpu_nodes(drm, dev), (dev / "card1", dev / "renderD128"))

    def test_fails_closed_without_physical_render_node(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / "sys").mkdir()
            (root / "dev").mkdir()
            with self.assertRaises(monitor.MonitorError):
                monitor.find_gpu_nodes(root / "sys", root / "dev")


class AptSourceTests(unittest.TestCase):
    def test_enables_repository_after_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = pathlib.Path(temporary) / "local.sources"
            source.write_text("Types: deb\nEnabled: no\n", encoding="utf-8")
            monitor.enable_local_repository(source)
            self.assertEqual(source.read_text(encoding="utf-8"), "Types: deb\nEnabled: yes\n")

    def test_rejects_unmanaged_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = pathlib.Path(temporary) / "local.sources"
            source.write_text("Types: deb\n", encoding="utf-8")
            with self.assertRaises(monitor.MonitorError):
                monitor.enable_local_repository(source)


class RepositoryPermissionsTests(unittest.TestCase):
    def test_published_tree_is_readable_by_apt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary) / "staging"
            nested = root / "dists" / "stable"
            nested.mkdir(parents=True)
            package_index = nested / "Packages"
            package_index.write_text("Package: kwin-wayland\n", encoding="utf-8")
            root.chmod(0o700)
            nested.chmod(0o700)
            package_index.chmod(0o600)

            monitor.make_repository_readable(root)

            self.assertEqual(root.stat().st_mode & 0o777, 0o755)
            self.assertEqual(nested.stat().st_mode & 0o777, 0o755)
            self.assertEqual(package_index.stat().st_mode & 0o777, 0o644)


class RepositoryMetadataTests(unittest.TestCase):
    def test_command_capture_does_not_mix_stderr_into_stdout(self):
        output = monitor.run(
            ["python3", "-c", "import sys; print('metadata'); print('diagnostic', file=sys.stderr)"],
            capture=True,
        )
        self.assertEqual(output, "metadata\n")

    def test_rejects_diagnostic_appended_to_packages_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = pathlib.Path(temporary)
            index = repository / "dists" / "stable" / "main" / "binary-amd64" / "Packages"
            index.parent.mkdir(parents=True)
            index.write_text(
                "Package: kwin-wayland\nVersion: 1+local1\n\n"
                "dpkg-scanpackages: info: Wrote 1 entries\n",
                encoding="utf-8",
            )
            self.assertFalse(monitor.repository_is_valid(repository))

    def test_accepts_package_stanzas(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = pathlib.Path(temporary)
            index = repository / "dists" / "stable" / "main" / "binary-amd64" / "Packages"
            index.parent.mkdir(parents=True)
            index.write_text("Package: kwin-wayland\nVersion: 1+local1\n", encoding="utf-8")
            self.assertTrue(monitor.repository_is_valid(repository))


class PackagingTests(unittest.TestCase):
    def test_postinst_exports_the_generated_key_by_fingerprint(self):
        postinst = (MODULE_PATH.parents[1] / "debian" / "postinst").read_text(encoding="utf-8")
        self.assertIn('--export "$fingerprint"', postinst)
        self.assertIn('[ -s "$keyring" ]', postinst)
        self.assertNotIn("--export kwin-ctm-monitor", postinst)

    def test_apt_hook_is_the_only_automatic_trigger(self):
        apt_hook = (MODULE_PATH.parents[1] / "apt" / "99kwin-ctm-monitor").read_text(encoding="utf-8")
        self.assertIn("APT::Update::Post-Invoke-Success", apt_hook)
        self.assertFalse((MODULE_PATH.parents[1] / "systemd" / "kwin-ctm-monitor.path").exists())

    def test_official_kwin_remains_a_recovery_candidate(self):
        preferences = (MODULE_PATH.parents[1] / "apt" / "kwin-ctm-monitor.pref").read_text(encoding="utf-8")
        self.assertNotIn('Pin: origin "archive.neon.kde.org"', preferences)
        self.assertNotIn("Pin-Priority: -1", preferences)

    def test_ctm_restore_is_not_globally_autostarted(self):
        install = (MODULE_PATH.parents[1] / "debian" / "install").read_text(encoding="utf-8")
        self.assertIn("cli/kwinctmctl-restore usr/bin", install)
        self.assertNotIn("etc/xdg/autostart", install)
        self.assertFalse((MODULE_PATH.parents[1] / "autostart" / "kwin-ctm-restore.desktop").exists())
        postinst = (MODULE_PATH.parents[1] / "debian" / "postinst").read_text(encoding="utf-8")
        self.assertIn("rm -f /etc/xdg/autostart/kwin-ctm-restore.desktop", postinst)

    def test_systemd_creates_the_volatile_runtime_directory(self):
        postinst = (MODULE_PATH.parents[1] / "debian" / "postinst").read_text(encoding="utf-8")
        self.assertIn("#DEBHELPER#", postinst)
        self.assertIn("systemctl start --no-block kwin-ctm-monitor.service", postinst)
        service = (MODULE_PATH.parents[1] / "systemd" / "kwin-ctm-monitor.service").read_text(encoding="utf-8")
        self.assertIn("RuntimeDirectory=kwin-ctm-monitor", service)


class PatchContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patch = (MODULE_PATH.parents[1] / "patches" / "custom-output-ctm.patch").read_text(encoding="utf-8")

    def test_persisted_ctm_is_never_restored_automatically(self):
        # A CTM is only ever set through the interactive D-Bus API against an
        # already-running session; automatic output setup at startup must
        # never feed a persisted matrix back into the live DRM configuration.
        self.assertIn("customSdrCtm is intentionally not restored here", self.patch)
        self.assertNotIn("bool testCustomCtm", self.patch)
        self.assertNotIn("config.source == OutputConfiguration::Source::User", self.patch)

    def test_ctm_is_isolated_from_icc_pipeline(self):
        self.assertIn("ColorPipeline customPipeline", self.patch)
        self.assertIn("customPipeline.addMatrix", self.patch)
        self.assertNotIn("colorPipeline.addMatrix(*next.customSdrCtm", self.patch)

    def test_failed_presentation_returns_to_identity(self):
        self.assertIn("CustomSdrCtmStatus::Rejected", self.patch)
        self.assertIn("failed the full presentation test", self.patch)
        self.assertIn("m_pipeline->setCrtcColorPipeline(ColorPipeline{});", self.patch)

    def test_activation_is_synchronous_with_the_hardware_test(self):
        # Inferring "the display is now stable" from render-loop signals
        # (a presented-frame callback) is unreliable: plasmalogin reuses the
        # same compositor process across the greeter and the session, so
        # those signals fire continuously regardless of session state.
        # Activation must happen directly after a successful synchronous
        # atomic test, with no async wait.
        self.assertNotIn("AwaitingFrame", self.patch)
        self.assertNotIn("DrmOutputCtmFeedback", self.patch)
        self.assertNotIn("customSdrCtmFramePresented", self.patch)
        self.assertIn("m_customSdrCtmStatus = CustomSdrCtmStatus::Active;", self.patch)

    def test_persistence_and_dbus_share_validation(self):
        self.assertGreaterEqual(self.patch.count("BackendOutput::isValidCustomSdrCtm"), 3)


RESTORE_PATH = pathlib.Path(__file__).parents[1] / "cli" / "kwinctmctl-restore"
RESTORE_LOADER = importlib.machinery.SourceFileLoader("kwinctmctl_restore", str(RESTORE_PATH))
RESTORE_SPEC = importlib.util.spec_from_loader(RESTORE_LOADER.name, RESTORE_LOADER)
restore = importlib.util.module_from_spec(RESTORE_SPEC)
RESTORE_LOADER.exec_module(restore)


class RestoreScriptTests(unittest.TestCase):
    def test_finds_ctms_nested_under_the_saved_output_config(self):
        data = {
            "data": [
                {"uuid": "aaa", "customSdrCtm": list(range(9))},
                {"uuid": "bbb", "name": "HDMI-1"},
            ]
        }
        self.assertEqual(list(restore.find_saved_ctms(data)), [("aaa", list(range(9)))])

    def test_ignores_malformed_or_partial_entries(self):
        data = [{"uuid": "aaa", "customSdrCtm": [1, 2, 3]}, {"customSdrCtm": list(range(9))}, "not-a-dict"]
        self.assertEqual(list(restore.find_saved_ctms(data)), [])


class BuildBoundaryTests(unittest.TestCase):
    def test_debian_changelog_tool_runs_inside_container(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        prepare_source = source.split("def prepare_source", 1)[1].split("def find_gpu_nodes", 1)[0]
        container_build = source.split("def build_in_docker", 1)[1].split("def validate_packages", 1)[0]
        self.assertNotIn("dch", prepare_source)
        self.assertIn('dch --newversion "$LOCAL_VERSION"', container_build)


    def test_container_build_uses_gcc_14_from_initial_configuration(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        container_build = source.split("def build_in_docker", 1)[1].split("def validate_packages", 1)[0]
        self.assertIn("g++-14 gcc-14", container_build)
        self.assertIn("export CC=/usr/bin/gcc-14", container_build)
        self.assertIn("export CXX=/usr/bin/g++-14", container_build)
        self.assertLess(container_build.index("export CXX="), container_build.index("override_dh_auto_configure"))


if __name__ == "__main__":
    unittest.main()
