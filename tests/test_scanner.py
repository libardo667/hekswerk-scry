"""The scanner: chokepoints, knots, and unused steps."""

import unittest

from hekswerk_scry.checker import scan_proof_map
from tests.helpers import KNOT_STEPS, example, make_map, make_step


class TestScanner(unittest.TestCase):
    def test_example_has_one_chokepoint_one_knot_and_one_unused_step(self) -> None:
        scan = scan_proof_map(example())
        self.assertEqual([c.step_id for c in scan.chokepoints], ["fraction-below-one"])
        self.assertEqual(len(scan.knots), 1)
        knot = scan.knots[0]
        self.assertEqual(set(knot.step_ids), set(KNOT_STEPS))
        self.assertEqual(knot.exit_step_id, "shift-positive")
        self.assertEqual(knot.inputs, ("x >= 0",))
        self.assertEqual(knot.output, "x + 7 > 0")
        self.assertEqual([u.step_id for u in scan.unused_steps], ["square-nonneg"])

    def test_knots_can_branch_not_just_run_in_a_line(self) -> None:
        # cube-positive, cube-split and square-positive all feed shift-positive side by side.
        knot = scan_proof_map(example()).knots[0]
        parents = set(example().steps["shift-positive"].depends_on)
        self.assertEqual(parents, {"cube-positive", "cube-split", "square-positive"})
        self.assertTrue(parents < set(knot.step_ids))

    def test_a_straight_line_proof_is_all_spine_and_no_knots(self) -> None:
        steps = [
            make_step("a", "p1", ["s"]),
            make_step("b", "p2", ["p1"], ["a"]),
            make_step("c", "p3", ["p2"], ["b"]),
            make_step("d", "goal", ["p3"], ["c"]),
        ]
        scan = scan_proof_map(make_map(steps, "d", ["s"]))
        self.assertEqual([c.step_id for c in scan.chokepoints], ["a", "b", "c"])
        self.assertEqual(scan.knots, ())

    def test_only_the_largest_of_nested_knots_is_reported(self) -> None:
        steps = [
            make_step("k1", "f1", ["s"]),
            make_step("k2", "f2", ["f1"], ["k1"]),
            make_step("k3", "f3", ["f2"], ["k2"]),
            make_step("k4", "f4", ["f3"], ["k3"]),
            make_step("side", "g", ["s"]),
            make_step("end", "goal", ["f4", "g"], ["k4", "side"]),
        ]
        scan = scan_proof_map(make_map(steps, "end", ["s"]))
        self.assertEqual([k.step_ids for k in scan.knots], [("k1", "k2", "k3", "k4")])

    def test_minimum_knot_size_can_be_changed(self) -> None:
        self.assertEqual(scan_proof_map(example(), min_knot_steps=5).knots, ())

    def test_scanning_a_map_without_its_goal_step_explains_why_it_cannot(self) -> None:
        with self.assertRaisesRegex(ValueError, "goal step 'nope' is not in the map"):
            scan_proof_map(make_map([make_step("a", "p")], "nope", goal="p"))


if __name__ == "__main__":
    unittest.main()
