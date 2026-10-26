import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("retention", Path(__file__).with_name("retention.py"))
retention = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retention)


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

    def test_private_venv_inside_a_revision_prevents_deletion(self):
        self.promote(self.names[0])
        self.promote(self.names[1])
        protected = self.releases / self.names[0] / ".venv"
        protected.mkdir()
        (protected / "personal.txt").write_text("must stay")
        result = self.promote(self.names[2])
        self.assertTrue(any("protected-payload" in reason for reason in result["blocked"]))
        self.assertEqual((protected / "personal.txt").read_text(), "must stay")

    def test_unhealthy_activation_never_moves_selectors(self):
        self.promote(self.names[0])
        with patch.object(retention, "runtime_health", side_effect=RuntimeError("inactive")):
            with self.assertRaisesRegex(RuntimeError, "inactive"):
                self.promote(self.names[1])
        self.assertEqual((self.base / "current").resolve().name, self.names[0])
        self.assertFalse((self.base / "rollback").exists())


if __name__ == "__main__":
    unittest.main()
