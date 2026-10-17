"""What-If tests and Breakage reports."""

import unittest

from hekswerk_scry.checker import WIRING_WHAT_IF_CAVEAT, run_what_if
from hekswerk_scry.core.enums import CheckKind, WhatIfKind
from hekswerk_scry.models import WhatIfChange
from tests.helpers import example, make_map, make_step


def remove(step_id: str) -> WhatIfChange:
    return WhatIfChange(WhatIfKind.REMOVE_STEP, step_id)


def drop(fact: str) -> WhatIfChange:
    return WhatIfChange(WhatIfKind.DROP_STARTING_FACT, fact)


class TestWhatIf(unittest.TestCase):
    def test_removing_a_load_bearing_step_reports_each_casualty_in_order(self) -> None:
        report = run_what_if(example(), remove("cube-split"))
        self.assertEqual(
            [(b.step_id, b.steps_away, b.hit_directly) for b in report.broken_steps],
            [
                ("shift-positive", 1, True),
                ("fraction-below-one", 2, False),
                ("fraction-not-one", 3, False),
            ],
        )
        self.assertTrue(report.goal_reached_before)
        self.assertFalse(report.goal_reached_after)
        self.assertIn("The goal is no longer reached", report.headline)
        self.assertIn("(x + 7)^3 = (x + 7) * (x + 7)^2", report.broken_steps[0].reasons[0])

    def test_dropping_a_starting_fact(self) -> None:
        report = run_what_if(example(), drop("  x >=  0 "))
        direct = {b.step_id for b in report.broken_steps if b.hit_directly}
        self.assertEqual(direct, {"cube-positive", "square-positive"})
        self.assertEqual(report.broken_steps[-1].step_id, "fraction-not-one")
        self.assertEqual(report.broken_steps[-1].steps_away, 4)

    def test_removing_an_unused_step_breaks_nothing_and_does_not_overclaim(self) -> None:
        report = run_what_if(example(), remove("square-nonneg"))
        self.assertEqual(report.broken_steps, ())
        self.assertTrue(report.headline.startswith("Nothing relies on this"))
        # The first draft called such steps "redundant search noise". Scry must not.
        self.assertNotIn("noise", report.headline + report.explanation)
        self.assertEqual(report.caveat, WIRING_WHAT_IF_CAVEAT)
        self.assertIs(report.checked_by, CheckKind.WIRING)

    def test_removing_the_goal_step(self) -> None:
        report = run_what_if(example(), remove("fraction-not-one"))
        self.assertEqual(report.broken_steps, ())
        self.assertFalse(report.goal_reached_after)
        self.assertIn("goal is no longer reached", report.headline)

    def test_steps_broken_before_the_change_are_not_blamed_on_it(self) -> None:
        proof_map = make_map(
            [
                make_step("a", "p", ["s"]),
                make_step("lonely", "q", ["nowhere"]),
                make_step("b", "goal", ["p"], ["a"]),
            ],
            "b",
            ["s"],
        )
        report = run_what_if(proof_map, remove("a"))
        self.assertEqual([b.step_id for b in report.broken_steps], ["b"])
        self.assertEqual(report.already_broken_step_ids, ("lonely",))

    def test_unknown_targets_are_explained(self) -> None:
        with self.assertRaisesRegex(ValueError, "no step 'ghost'"):
            run_what_if(example(), remove("ghost"))
        with self.assertRaisesRegex(ValueError, "not one of this map's starting facts"):
            run_what_if(example(), drop("x > 100"))

    def test_maps_with_loops_are_refused(self) -> None:
        proof_map = make_map(
            [make_step("a", "p", ["q"], ["b"]), make_step("b", "q", ["p"], ["a"])], "a"
        )
        with self.assertRaisesRegex(ValueError, "loop"):
            run_what_if(proof_map, remove("a"))


if __name__ == "__main__":
    unittest.main()
