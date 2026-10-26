"""Regression tests for native retirement and explicit rollback."""
import unittest
from unittest.mock import patch
from pathlib import Path

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

    def test_extensionless_executable_referencing_old_release_blocks_prune(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        native_bin = self.base / "native-bin"
        native_bin.mkdir()
        wrapper = native_bin / "desktop-commander-wrapper"
        wrapper.write_text("#!/bin/sh\nexec node " + str(self.releases / self.names[0] / "dist/index.js") + "\n")
        wrapper.chmod(0o755)
        result = test_retention.retention.promote(
            self.names[2], host="minipc", base=self.base, consumer_paths=[native_bin])
        self.assertTrue(any("unit-or-config" in x for x in result["blocked"]), result)
        self.assertTrue((self.releases / self.names[0]).is_dir())

    def test_nonexecutable_interpreter_script_referencing_old_release_blocks_prune(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        native_bin = self.base / "native-bin"
        native_bin.mkdir()
        script = native_bin / "legacy.sh"
        script.write_text("#!/bin/sh\nnode " + str(self.releases / self.names[0] / "dist/index.js") + "\n")
        script.chmod(0o644)  # systemd may use ExecStart=/bin/sh /path/legacy.sh
        unit = self.base / "other.service"
        unit.write_text("ExecStart=/bin/sh " + str(script))
        result = test_retention.retention.promote(
            self.names[2], host="minipc", base=self.base, consumer_paths=[native_bin, unit])
        self.assertTrue(any("unit-or-config:legacy.sh" in x for x in result["blocked"]), result)
        self.assertTrue((self.releases / self.names[0]).is_dir())

    def test_nonexecutable_node_script_referencing_old_release_blocks_prune(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        scripts = self.base / "hosting"
        scripts.mkdir()
        entry = scripts / "legacy.mjs"
        entry.write_text("const old = '" + str(self.releases / self.names[0]) + "';\n")
        entry.chmod(0o644)
        unit = self.base / "old-node.service"
        unit.write_text("ExecStart=node " + str(entry))
        result = test_retention.retention.promote(
            self.names[2], host="minipc", base=self.base, consumer_paths=[unit])
        self.assertTrue(any("unit-or-config:legacy.mjs" in x for x in result["blocked"]), result)
        self.assertTrue((self.releases / self.names[0]).is_dir())

    def test_first_promotion_abandonment_restores_no_rollback(self):
        self.promote(self.names[0])
        point = test_retention.retention._point

        def interrupted(base, label, revision):
            if label == "current" and revision == self.names[1]:
                raise RuntimeError("first-promotion-interrupted")
            return point(base, label, revision)

        with patch.object(test_retention.retention, "_point", side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, "first-promotion-interrupted"):
                self.promote(self.names[1])
        self.assertEqual((self.base / "rollback").resolve().name, self.names[0])
        self.promote(self.names[0])
        self.assertEqual((self.base / "current").resolve().name, self.names[0])
        self.assertFalse((self.base / "rollback").exists())

    def test_cancelled_first_promotion_discards_pending_rollback_symlink(self):
        self.promote(self.names[0])
        real_replace = Path.replace

        def interrupted_replace(path, target):
            if path == self.base / ".rollback.new":
                raise RuntimeError("interrupted-first-rollback-rename")
            return real_replace(path, target)

        with patch.object(Path, "replace", interrupted_replace):
            with self.assertRaisesRegex(RuntimeError, "interrupted-first-rollback-rename"):
                self.promote(self.names[1])
        self.assertTrue((self.base / ".rollback.new").is_symlink())
        self.promote(self.names[0])
        self.assertFalse((self.base / ".rollback.new").exists())
        self.assertFalse((self.base / "rollback").exists())

    def test_cancelled_revert_discards_exact_pending_current_selector(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        self.promote(self.names[2])
        real_replace = Path.replace

        def interrupted_replace(path, target):
            if path == self.base / ".current.new":
                raise RuntimeError("interrupted-current-rename")
            return real_replace(path, target)

        with patch.object(Path, "replace", interrupted_replace):
            with self.assertRaisesRegex(RuntimeError, "interrupted-current-rename"):
                self.promote(self.names[1])
        self.assertTrue((self.base / ".current.new").is_symlink())
        self.promote(self.names[2])  # Original C returned healthy.
        self.assertFalse((self.base / ".current.new").exists())
        self.assertEqual((self.base / "current").resolve().name, self.names[2])
        self.assertEqual((self.base / "rollback").resolve().name, self.names[1])

    def test_interrupted_plain_revert_restores_rollback_without_pending_retirement(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        self.promote(self.names[2])  # A retired, leaving exactly C and B.
        point = test_retention.retention._point

        def interrupted(base, label, revision):
            if label == "current" and revision == self.names[1]:
                raise RuntimeError("simulated-plain-revert-interruption")
            return point(base, label, revision)

        with patch.object(test_retention.retention, "_point", side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, "simulated-plain-revert-interruption"):
                self.promote(self.names[1])
        self.promote(self.names[2])  # Original C service returned healthy.
        self.assertEqual((self.base / "current").resolve().name, self.names[2])
        self.assertEqual((self.base / "rollback").resolve().name, self.names[1])
        self.assertEqual(sorted(x.name for x in self.releases.iterdir()), self.names[1:])

    def test_interrupted_revert_keeps_exact_rollback_after_original_service_returns(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        with patch.object(test_retention.retention, "process_references",
                          return_value=[(4321, str(self.releases / self.names[0]))]):
            self.assertTrue(self.promote(self.names[2])["blocked"])
            point = test_retention.retention._point

            def interrupted(base, label, revision):
                if label == "current" and revision == self.names[1]:
                    raise RuntimeError("simulated-interrupted-revert")
                return point(base, label, revision)

            with patch.object(test_retention.retention, "_point", side_effect=interrupted):
                with self.assertRaisesRegex(RuntimeError, "simulated-interrupted-revert"):
                    self.promote(self.names[1])
            recovered = self.promote(self.names[2])
        self.assertEqual((self.base / "current").resolve().name, self.names[2])
        self.assertEqual((self.base / "rollback").resolve().name, self.names[1])
        self.assertEqual((self.base / "retired").resolve().name, self.names[0])
        self.assertTrue((self.releases / self.names[1]).is_dir())
        self.assertTrue((self.releases / self.names[0]).is_dir())
        self.assertTrue(recovered["blocked"])

    def test_revert_committed_before_journal_cleanup_can_restore_original_service(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        with patch.object(test_retention.retention, "process_references",
                          return_value=[(4321, str(self.releases / self.names[0]))]):
            self.promote(self.names[2])
            journal = self.base / "revert-intent"
            unlink = Path.unlink

            def interrupt_journal(path, *args, **kwargs):
                if path == journal:
                    raise RuntimeError("crash-after-current-revert")
                return unlink(path, *args, **kwargs)

            with patch.object(Path, "unlink", interrupt_journal):
                with self.assertRaisesRegex(RuntimeError, "crash-after-current-revert"):
                    self.promote(self.names[1])
            self.assertEqual((self.base / "current").resolve().name, self.names[1])
            self.assertEqual((self.base / "rollback").resolve().name, self.names[2])
            recovered = self.promote(self.names[2])
        self.assertTrue(recovered["blocked"])
        self.assertEqual((self.base / "current").resolve().name, self.names[2])
        self.assertEqual((self.base / "rollback").resolve().name, self.names[1])
        self.assertEqual((self.base / "retired").resolve().name, self.names[0])
        self.assertFalse(journal.exists())
