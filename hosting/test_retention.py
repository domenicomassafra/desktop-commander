import importlib.util
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).parent))
from release_manifest import seal

spec = importlib.util.spec_from_file_location("retention", Path(__file__).with_name("retention.py"))
retention = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retention)
REAL_OPEN_FILE_REFERENCES = retention.open_file_references
REAL_RUNTIME_HEALTH = retention.runtime_health


class ImmutablePromotionTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.base = Path(self.folder.name) / "desktop-commander"
        self.releases = self.base / "releases"
        self.releases.mkdir(parents=True)
        self.names = ["a" * 40, "b" * 40, "c" * 40]
        for name in self.names:
            path = self.releases / name / "dist"
            path.mkdir(parents=True)
            (path / "index.js").write_text("// built\n")
            (self.releases / name / "package.json").write_text(
                json.dumps({"name": "@wonderwhy-er/desktop-commander"}))
            if name == self.names[0]:
                dep = self.releases / name / "node_modules" / "package" / "state"
                dep.mkdir(parents=True)
                (dep / "index.js").write_text("// bundled dependency")
            seal(self.releases / name)
        self.probes = patch.multiple(retention, runtime_health=lambda *args: None,
                                     process_references=lambda *args: [],
                                     open_file_references=lambda *args: [])
        self.probes.start()
        self.addCleanup(self.probes.stop)

    def promote(self, name):
        return retention.promote(name, host="minipc", base=self.base,
                                 consumer_paths=[])

    def test_three_promotions_keep_exact_current_and_prior_healthy(self):
        self.promote(self.names[0])
        self.assertEqual((self.base / "current").resolve().name, self.names[0])
        self.assertFalse((self.base / "rollback").exists())
        self.promote(self.names[1])
        self.assertEqual((self.base / "rollback").resolve().name, self.names[0])
        result = self.promote(self.names[2])
        self.assertEqual(result["removed"], [self.names[0]])
        self.assertEqual(sorted(path.name for path in self.releases.iterdir()), self.names[1:])
        self.assertEqual((self.base / "current").resolve().name, self.names[2])
        self.assertEqual((self.base / "rollback").resolve().name, self.names[1])
        self.assertEqual(self.promote(self.names[2])["removed"], [])

    def test_live_process_blocks_prune_with_pid(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        with patch.object(retention, "process_references",
                          return_value=[(4321, str(self.releases / self.names[0]))]):
            result = self.promote(self.names[2])
        self.assertTrue(any("pid:4321" in reason for reason in result["blocked"]))
        self.assertTrue((self.releases / self.names[0]).exists())

    def test_blocked_retirement_retries_after_consumer_exits(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        with patch.object(retention, "process_references",
                          return_value=[(4321, str(self.releases / self.names[0]))]):
            blocked = self.promote(self.names[2])
        self.assertTrue(blocked["blocked"])
        self.assertEqual((self.base / "rollback").resolve().name, self.names[1])
        resumed = self.promote(self.names[2])
        self.assertEqual(resumed["removed"], [self.names[0]])
        self.assertFalse((self.base / "retired").exists())
        self.assertEqual(sorted(p.name for p in self.releases.iterdir()), self.names[1:])

    def test_promoting_exact_rollback_does_not_retire_the_selected_release(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        self.promote(self.names[2])
        reverted = self.promote(self.names[1])
        self.assertEqual(reverted["blocked"], [])
        self.assertEqual(reverted["removed"], [])
        self.assertFalse((self.base / "retired").is_symlink())
        self.assertEqual((self.base / "rollback").resolve().name, self.names[2])
        restored = self.promote(self.names[2])
        self.assertEqual(restored["blocked"], [])
        self.assertEqual((self.base / "rollback").resolve().name, self.names[1])

    def test_unit_and_symlink_block_prune(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        unit = self.base / "desktop-commander.service"
        unit.write_text("ExecStart=" + str(self.releases / self.names[0]))
        link = self.base / "other-consumer"
        link.symlink_to(self.releases / self.names[0])
        result = retention.promote(self.names[2], host="minipc", base=self.base,
                                   consumer_paths=[unit])
        self.assertTrue(any("unit-or-config" in reason for reason in result["blocked"]))
        self.assertTrue(any("symlink" in reason for reason in result["blocked"]))
        self.assertTrue((self.releases / self.names[0]).exists())

    def test_open_file_blocks_prune(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        with patch.object(retention, "open_file_references",
                          return_value=[str(self.releases / self.names[0] / "dist/index.js")]):
            result = self.promote(self.names[2])
        self.assertTrue(any("open-file" in reason for reason in result["blocked"]))
        self.assertTrue((self.releases / self.names[0]).exists())

    def test_uncertain_revision_and_non_release_data_are_preserved(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        staging = self.releases / "staging"
        staging.mkdir()
        unknown = self.releases / "unexpected-version"
        (unknown / "dist").mkdir(parents=True)
        (unknown / "dist/index.js").write_text("present")
        result = self.promote(self.names[2])
        self.assertTrue(any("uncertain-revision" in reason for reason in result["blocked"]))
        self.assertTrue((self.releases / self.names[0]).exists())
        self.assertTrue(staging.exists())
        self.assertTrue(unknown.exists())

    def test_interrupted_selector_update_resumes_from_pending_retirement(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        (self.base / "retired").symlink_to(Path("releases") / self.names[0])
        (self.base / "rollback").unlink()
        (self.base / "rollback").symlink_to(Path("releases") / self.names[1])
        result = self.promote(self.names[2])
        self.assertEqual(result["removed"], [self.names[0]])
        self.assertEqual((self.base / "rollback").resolve().name, self.names[1])
        self.assertEqual((self.base / "current").resolve().name, self.names[2])

    def test_interrupted_between_first_rollback_and_current_can_retry(self):
        shutil.rmtree(self.releases / self.names[2])  # This scenario has only A and B.
        self.promote(self.names[0])
        original = retention._point

        def interrupted(base, label, release):
            if label == "current":
                raise RuntimeError("simulated interruption")
            return original(base, label, release)

        with patch.object(retention, "_point", side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, "simulated interruption"):
                self.promote(self.names[1])
        self.assertEqual((self.base / "rollback").resolve().name, self.names[0])
        result = self.promote(self.names[1])
        self.assertEqual(result["blocked"], [])
        self.assertEqual((self.base / "current").resolve().name, self.names[1])
        self.assertEqual((self.base / "rollback").resolve().name, self.names[0])
        self.assertTrue((self.releases / self.names[0]).exists())

    def test_deleted_retired_release_marker_recovers_after_interruption(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        retired = self.base / "retired"
        real_unlink = Path.unlink

        def interrupted_unlink(path, *args, **kwargs):
            if path == retired:
                raise RuntimeError("interrupted-after-rmtree")
            return real_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", interrupted_unlink):
            with self.assertRaisesRegex(RuntimeError, "interrupted-after-rmtree"):
                self.promote(self.names[2])
        self.assertFalse((self.releases / self.names[0]).exists())
        self.assertTrue(retired.is_symlink())
        result = self.promote(self.names[2])
        self.assertEqual(result["blocked"], [])
        self.assertFalse(retired.is_symlink())

    def test_partial_lsof_output_blocks_pruning(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        scan = subprocess.CompletedProcess([], 0, "n/unrelated/file\n", "lsof: WARNING: partial scan\n")
        with patch.object(retention.subprocess, "run", return_value=scan), \
             patch.object(retention, "open_file_references", REAL_OPEN_FILE_REFERENCES):
            result = self.promote(self.names[2])
        self.assertTrue(any("incomplete-lsof-scan" in reason for reason in result["blocked"]))
        self.assertTrue((self.releases / self.names[0]).exists())

    def test_other_native_unit_dropin_referencing_old_release_blocks_prune(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        directory = self.base / "user-units"
        dropin = directory / "other.service.d" / "override.conf"
        dropin.parent.mkdir(parents=True)
        dropin.write_text("Environment=ENTRY=" + str(self.releases / self.names[0]))
        result = retention.promote(self.names[2], host="minipc", base=self.base,
                                   consumer_paths=[directory])
        self.assertTrue(any("unit-or-config" in reason for reason in result["blocked"]))
        self.assertTrue((self.releases / self.names[0]).exists())

    def test_studio_gateway_parent_without_healthy_node_cannot_promote(self):
        self.promote(self.names[0])
        path = self.releases / self.names[1]
        payload = plistlib.dumps({"ProgramArguments": ["supergateway", "--stdio",
                          "node " + str(path / "dist/index.js")]})
        status = subprocess.CompletedProcess([], 0, "state = running\npid = 4321\n", "")
        with patch.object(retention, "runtime_health", REAL_RUNTIME_HEALTH), \
             patch.object(retention, "_process_tree", return_value=[
                 (4321, 1, "supergateway --stdio node " + str(path / "dist/index.js"))]), \
             patch.object(Path, "read_bytes", return_value=payload), \
             patch.object(retention.subprocess, "run", return_value=status):
            with self.assertRaisesRegex(RuntimeError, "missing-studio-node-child"):
                retention.runtime_health("studio", path, self.base)

    def test_unknown_payload_inside_sha_directory_blocks_prune(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        private = self.releases / self.names[0] / "personal-audio.dat"
        private.write_bytes(b"do not delete")
        result = self.promote(self.names[2])
        self.assertTrue(any("unrecognized-content" in reason
                            for reason in result["blocked"]))
        self.assertEqual(private.read_bytes(), b"do not delete")

    def test_private_venv_inside_a_revision_prevents_deletion(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        protected = self.releases / self.names[0] / ".venv"
        protected.mkdir()
        (protected / "personal.txt").write_text("must stay")
        result = self.promote(self.names[2])
        self.assertTrue(any("protected-payload" in reason for reason in result["blocked"]))
        self.assertEqual((protected / "personal.txt").read_text(), "must stay")

    def test_nested_private_data_inside_hosting_prevents_deletion(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        protected = self.releases / self.names[0] / "hosting" / "backup"
        protected.mkdir(parents=True)
        (protected / "private.txt").write_text("must stay")
        result = self.promote(self.names[2])
        self.assertTrue(any("protected-payload" in reason for reason in result["blocked"]))
        self.assertEqual((protected / "private.txt").read_text(), "must stay")

    def test_nested_data_inside_hosting_prevents_deletion(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        protected = self.releases / self.names[0] / "hosting" / "data"
        protected.mkdir(parents=True)
        (protected / "owner.sqlite").write_text("owner-only")
        result = self.promote(self.names[2])
        self.assertTrue(result["blocked"], result)
        self.assertEqual((protected / "owner.sqlite").read_text(), "owner-only")

    def test_changed_compiled_payload_after_build_seal_prevents_deletion(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        entry = self.releases / self.names[0] / "dist/index.js"
        entry.write_text("// modified after sealed build\n")
        result = self.promote(self.names[2])
        self.assertTrue(any("unverified-release-payload" in reason
                            for reason in result["blocked"]))
        self.assertEqual(entry.read_text(), "// modified after sealed build\n")

    def test_package_module_state_is_not_mistaken_for_private_runtime_state(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        package = self.releases / self.names[0] / "node_modules" / "package" / "state"
        self.assertTrue((package / "index.js").is_file())
        result = self.promote(self.names[2])
        self.assertEqual(result["blocked"], [])
        self.assertEqual(result["removed"], [self.names[0]])

    def test_unhealthy_activation_never_moves_selectors(self):
        self.promote(self.names[0])
        with patch.object(retention, "runtime_health", side_effect=RuntimeError("inactive")):
            with self.assertRaisesRegex(RuntimeError, "inactive"):
                self.promote(self.names[1])
        self.assertEqual((self.base / "current").resolve().name, self.names[0])
        self.assertFalse((self.base / "rollback").exists())


if __name__ == "__main__":
    unittest.main()
