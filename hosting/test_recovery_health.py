"""A health failure must never mutate interrupted native selection state."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import test_retention as fixture_module


class InterruptedActivationHealthTest(unittest.TestCase):
    def test_unhealthy_recovery_does_not_change_existing_selectors(self):
        fixture = fixture_module.ImmutablePromotionTest(
            "test_three_promotions_keep_exact_current_and_prior_healthy")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.promote(fixture.names[0])
        fixture.promote(fixture.names[1])
        previous_point = fixture_module.retention._point

        def interrupt(base, label, revision):
            if label == "current":
                raise RuntimeError("crashed-during-activation")
            return previous_point(base, label, revision)

        with patch.object(fixture_module.retention, "_point", side_effect=interrupt):
            with self.assertRaisesRegex(RuntimeError, "crashed-during-activation"):
                fixture.promote(fixture.names[2])

        def selectors():
            return tuple((fixture.base / name).readlink()
                         for name in ("current", "rollback", "retired"))

        before = selectors()
        with patch.object(fixture_module.retention, "runtime_health",
                          side_effect=RuntimeError("native-service-unhealthy")):
            with self.assertRaisesRegex(RuntimeError, "native-service-unhealthy"):
                fixture.promote(fixture.names[1])
        self.assertEqual(selectors(), before)


if __name__ == "__main__":
    unittest.main()
