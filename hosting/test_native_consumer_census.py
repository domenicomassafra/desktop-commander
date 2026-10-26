"""Retirement needs evidence about native consumers beyond absolute paths."""
import subprocess
import unittest
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
