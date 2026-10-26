"""Retirement needs evidence about native consumers beyond absolute paths."""
import subprocess
import plistlib
import unittest
from pathlib import Path
from unittest.mock import patch

import test_retention


class NativeConsumerCensusTest(unittest.TestCase):
    setUp = test_retention.ImmutablePromotionTest.setUp
    promote = test_retention.ImmutablePromotionTest.promote

    def test_running_relative_release_process_blocks_retirement(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        cmd = "node releases/" + self.names[0] + "/dist/index.js"
        with patch.object(test_retention.retention, "process_references",
                          return_value=[(4321, cmd)]):
            result = self.promote(self.names[2])
        self.assertTrue(any("pid:4321" in item for item in result["blocked"]), result)
        self.assertTrue((self.releases / self.names[0]).is_dir())

    def test_effective_systemd_user_unit_path_blocks_old_revision(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        unit_dir = self.base.parent / "systemd-shared-user-units"
        unit_dir.mkdir()
        (unit_dir / "legacy.service").write_text(
            "ExecStart=/bin/node " + str(self.releases / self.names[0] / "dist/index.js"))
        found = subprocess.CompletedProcess([], 0, str(unit_dir) + "\n", "")
        with patch.object(test_retention.retention.subprocess, "run", return_value=found) as query:
            result = test_retention.retention.promote(
                self.names[2], host="minipc", base=self.base)
        self.assertTrue(any("unit-or-config:legacy.service" in x for x in result["blocked"]), result)
        self.assertTrue((self.releases / self.names[0]).is_dir())
        query.assert_called_once()
        self.assertEqual(query.call_args.args[0], ["systemd-analyze", "--user", "unit-paths"])

    def test_systemd_path_unit_in_shared_directory_blocks_retirement(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        unit_dir = self.base.parent / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        (unit_dir / "legacy.path").write_text(
            "[Path]\nPathExists=" + str(self.releases / self.names[0] / "dist/index.js") + "\n")
        found = subprocess.CompletedProcess([], 0, str(unit_dir) + "\n", "")
        with patch.object(test_retention.retention.subprocess, "run", return_value=found):
            result = test_retention.retention.promote(
                self.names[2], host="minipc", base=self.base)
        self.assertTrue(any("unit-or-config:legacy.path" in x for x in result["blocked"]), result)
        self.assertTrue((self.releases / self.names[0]).is_dir())

    def test_unavailable_systemd_unit_census_never_deletes_history(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        failure = subprocess.CalledProcessError(1, ["systemd-analyze", "--user", "unit-paths"])
        with patch.object(test_retention.retention.subprocess, "run", side_effect=failure):
            with self.assertRaisesRegex(RuntimeError, "systemd-user-unit-census-unavailable"):
                test_retention.retention.promote(self.names[2], host="minipc", base=self.base)
        self.assertTrue((self.releases / self.names[0]).is_dir())

    def test_inactive_system_launchdaemon_blocks_retiring_revision(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        root = self.base.parent / "Library" / "LaunchDaemons"
        root.mkdir(parents=True)
        (root / "legacy.plist").write_bytes(plistlib.dumps({
            "Label": "org.example.legacy",
            "ProgramArguments": ["node", str(self.releases / self.names[0] / "dist/index.js")],
        }))
        with patch.object(test_retention.retention, "SYSTEM_LAUNCHD_ROOTS", (root,),
                          create=True):
            result = test_retention.retention.promote(
                self.names[2], host="studio", base=self.base)
        self.assertTrue(any("unit-or-config:legacy.plist" in x for x in result["blocked"]), result)
        self.assertTrue((self.releases / self.names[0]).is_dir())

    def test_utf16_xml_launchdaemon_blocks_retirement(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        root = self.base.parent / "Library" / "LaunchDaemons"
        root.mkdir(parents=True)
        payload = plistlib.dumps({
            "ProgramArguments": ["node", str(self.releases / self.names[0] / "dist/index.js")],
        }).decode("utf-8").replace('encoding="UTF-8"', 'encoding="UTF-16"').encode("utf-16")
        self.assertNotIn(self.names[0].encode(), payload)
        (root / "legacy-utf16.plist").write_bytes(payload)
        with patch.object(test_retention.retention, "SYSTEM_LAUNCHD_ROOTS", (root,)):
            result = test_retention.retention.promote(
                self.names[2], host="studio", base=self.base)
        self.assertTrue(any("unit-or-config:legacy-utf16.plist" in x for x in result["blocked"]), result)
        self.assertTrue((self.releases / self.names[0]).is_dir())

    def test_binary_unicode_launchagent_blocks_retirement(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        root = self.base.parent / "Library" / "LaunchAgents"
        root.mkdir(parents=True)
        payload = plistlib.dumps({
            "ProgramArguments": ["node", "café " + str(self.releases / self.names[0] / "dist/index.js")],
        }, fmt=plistlib.FMT_BINARY)
        self.assertNotIn(self.names[0].encode(), payload)
        (root / "legacy-binary.plist").write_bytes(payload)
        with patch.object(test_retention.retention, "SYSTEM_LAUNCHD_ROOTS", (root,)):
            result = test_retention.retention.promote(
                self.names[2], host="studio", base=self.base)
        self.assertTrue(any("unit-or-config:legacy-binary.plist" in x for x in result["blocked"]), result)
        self.assertTrue((self.releases / self.names[0]).is_dir())

    def test_malformed_native_plist_blocks_retirement(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        root = self.base.parent / "Library" / "LaunchDaemons"
        root.mkdir(parents=True)
        (root / "unknown.plist").write_bytes(b"bplist00broken")
        with patch.object(test_retention.retention, "SYSTEM_LAUNCHD_ROOTS", (root,)):
            result = test_retention.retention.promote(
                self.names[2], host="studio", base=self.base)
        self.assertTrue(any("unreadable-native-config:unknown.plist" in x
                            for x in result["blocked"]), result)
        self.assertTrue((self.releases / self.names[0]).is_dir())

    def test_unreadable_system_launchd_root_blocks_retirement(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        root = self.base.parent / "Library" / "LaunchDaemons"
        root.mkdir(parents=True)
        original = Path.lstat

        def unreadable(path, *args, **kwargs):
            if path == root:
                raise PermissionError("simulated launchd access denied")
            return original(path, *args, **kwargs)

        with patch.object(test_retention.retention, "SYSTEM_LAUNCHD_ROOTS", (root,)), \
             patch.object(Path, "lstat", unreadable):
            result = test_retention.retention.promote(
                self.names[2], host="studio", base=self.base)
        self.assertTrue(any("unreadable-native-root" in x for x in result["blocked"]), result)
        self.assertTrue((self.releases / self.names[0]).is_dir())
