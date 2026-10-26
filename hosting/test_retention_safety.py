"""Regression tests for native retirement and explicit rollback."""
import unittest
from unittest.mock import patch

import test_retention


class RetentionSafetyTest(unittest.TestCase):
    setUp = test_retention.ImmutablePromotionTest.setUp
    promote = test_retention.ImmutablePromotionTest.promote

    def test_live_rollback_symlink_prevents_prune(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        dependent = self.releases / self.names[1] / "node_modules" / "legacy-dependency"
        dependent.parent.mkdir(exist_ok=True)
        dependent.symlink_to(self.releases / self.names[0] / "dist", target_is_directory=True)
        result = self.promote(self.names[2])
        self.assertTrue(any("live-release-symlink" in x for x in result["blocked"]), result)
        self.assertTrue((self.releases / self.names[0] / "dist/index.js").is_file())

    def test_revert_to_rollback_with_pending_retirement(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        with patch.object(test_retention.retention, "process_references",
                          return_value=[(4321, str(self.releases / self.names[0]))]):
            self.assertTrue(self.promote(self.names[2])["blocked"])
            reverted = self.promote(self.names[1])
        self.assertTrue(any("pid:4321" in x for x in reverted["blocked"]))
        self.assertEqual((self.base / "current").resolve().name, self.names[1])
        self.assertEqual((self.base / "rollback").resolve().name, self.names[2])
        self.assertEqual((self.base / "retired").resolve().name, self.names[0])
        self.assertTrue((self.releases / self.names[0]).is_dir())
