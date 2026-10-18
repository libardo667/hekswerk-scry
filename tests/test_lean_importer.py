"""Turning a Lean trace into a proof map.

The fixture tests/fixtures/shifted_fraction.trace.json is real output of the Lean
exporter (lean/ScryExport) on lean/Examples/ShiftedFraction.lean.
"""

import copy
import json
import unittest
from pathlib import Path
from typing import Any

from hekswerk_scry.checker import check_wiring, scan_proof_map
from hekswerk_scry.files import proof_map_from_dict, proof_map_to_dict
from hekswerk_scry.lean.importer import (
    LeanImportError,
    trace_to_checked_map,
    trace_to_proof_map,
)
from hekswerk_scry.models import LeanSource, ProofMap

FIXTURE = Path(__file__).parent / "fixtures" / "shifted_fraction.trace.json"
SOURCE = LeanSource("Examples/ShiftedFraction.lean", "shifted_fraction_ne_one", "0" * 64)


def trace() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def lean_map() -> ProofMap:
    return trace_to_proof_map(trace(), SOURCE)


class TestImportedMap(unittest.TestCase):
    def test_statement_goal_and_starting_facts(self) -> None:
        proof_map = lean_map()
        self.assertEqual(proof_map.starting_facts, ("hx : x ≥ 0",))
        self.assertEqual(proof_map.goal, "Goal 1: x / (x + 7) ≠ 1")
        self.assertEqual(proof_map.goal_step_id, "s1")
        self.assertEqual(proof_map.lean_source, SOURCE)

    def test_everything_lean_reported_lines_up(self) -> None:
        self.assertTrue(check_wiring(lean_map()).passed)

    def test_steps_carry_their_code_and_position(self) -> None:
        step = lean_map().steps["s3"]
        self.assertEqual(
            step.views.code, "have cube_split : (x + 7) ^ 3 = (x + 7) * (x + 7) ^ 2 := by ring"
        )
        assert step.lean_range is not None
        self.assertEqual((step.lean_range.start_line, step.lean_range.start_column), (13, 2))

    def test_a_have_gets_its_own_why_step(self) -> None:
        why = lean_map().steps["s3-why1"]
        self.assertEqual(why.contract.proves, "cube_split : (x + 7) ^ 3 = (x + 7) * (x + 7) ^ 2")
        self.assertEqual(why.depends_on, ("s4",))  # the `ring` inside the `have`
        self.assertIsNone(why.lean_range)

    def test_arrows_follow_what_each_step_actually_used(self) -> None:
        proof_map = lean_map()
        # `exact pos_of_mul_pos_left cube_pos (le_of_lt sq_pos)` uses the rewritten cube_pos
        # (justified by the `rw` step) and the original sq_pos.
        self.assertEqual(set(proof_map.steps["s9"].depends_on), {"s8-why1", "s5-why1"})
        self.assertIn("hx : x ≥ 0", proof_map.steps["s2"].contract.assumes)

    def test_unchanged_copies_of_hypotheses_count_as_the_original(self) -> None:
        # `rw ... at cube_pos` re-creates sq_pos under a new identity; it is the same fact.
        steps = lean_map().steps
        self.assertFalse(any("version 2" in step.contract.proves for step in steps.values()))
        self.assertIn("sq_pos : (x + 7) ^ 2 > 0", steps["s9"].contract.assumes)

    def test_scan_finds_the_detour_and_the_unused_lemma(self) -> None:
        scan = scan_proof_map(lean_map())
        self.assertEqual([knot.output for knot in scan.knots], ["shift_pos : x + 7 > 0"])
        self.assertEqual(scan.knots[0].inputs, ("hx : x ≥ 0",))
        self.assertEqual([u.step_id for u in scan.unused_steps], ["s10-why1"])
        self.assertIn("Lean's finished proof doesn't rely on", scan.unused_steps[0].explanation)

    def test_map_survives_a_save_and_load(self) -> None:
        proof_map = lean_map()
        again = proof_map_from_dict(json.loads(json.dumps(proof_map_to_dict(proof_map))))
        self.assertEqual(again, proof_map)
        self.assertEqual(again.steps["s3"].lean_range, proof_map.steps["s3"].lean_range)

    def test_a_trace_that_loses_something_lean_recorded_is_refused(self) -> None:
        # Drop the step that proves `0 < x + 7` inside `have cube_pos`: Lean recorded it,
        # so a map without it no longer lines up, and the import must refuse.
        lossy = copy.deepcopy(trace())
        lossy["steps"] = [s for s in lossy["steps"] if s["index"] != 1]
        self.assertFalse(check_wiring(trace_to_proof_map(lossy, SOURCE)).passed)
        with self.assertRaisesRegex(LeanImportError, "Scry bug"):
            trace_to_checked_map(lossy, SOURCE)
        self.assertTrue(check_wiring(trace_to_checked_map(trace(), SOURCE)).passed)

    def test_a_trace_that_loses_a_hole_is_refused_even_though_it_lines_up(self) -> None:
        # Forget that the first step leaves the goal the next step works on, as reading a
        # step from a record with the next step's work already copied in would. No fact
        # goes missing, so the wiring still passes, but every later step now looks unused
        # although Lean's proof relies on it. The import must refuse.
        lossy = copy.deepcopy(trace())
        first = lossy["steps"][0]
        lost = first["leaves"][0]
        first["parts"][0]["holes"].remove(lost)
        worker = next(s for s in lossy["steps"] if any(p["goal"] == lost for p in s["parts"]))
        self.assertTrue(check_wiring(trace_to_proof_map(lossy, SOURCE)).passed)
        self.assertTrue(scan_proof_map(trace_to_proof_map(lossy, SOURCE)).unused_steps)
        refusal = f"step s{worker['index'] + 1} .*step s1 leaves for it"
        with self.assertRaisesRegex(LeanImportError, refusal):
            trace_to_checked_map(lossy, SOURCE)

    def test_a_sibling_goal_a_step_passes_along_is_held_by_the_step_that_left_it(self) -> None:
        # After `constructor`-like steps, the step on the first goal still lists the second
        # among its leftovers. Only the step that made it holds it, and that is enough.
        passing = copy.deepcopy(trace())
        first, second = passing["steps"][0], passing["steps"][1]
        sibling = first["leaves"][0]
        second["leaves"].append(sibling)
        self.assertNotIn(sibling, {h for p in second["parts"] for h in p["holes"]})
        trace_to_checked_map(passing, SOURCE)

    def test_an_unused_hint_is_an_unused_step_not_a_lost_hole(self) -> None:
        # `linarith [(by norm_num : (0 : ℝ) < 2)]`: Lean elaborates the hint, then doesn't use
        # it. Its block is in no step's piece, and that is what Lean did.
        fixture = Path(__file__).parent / "fixtures" / "unused_hint.trace.json"
        hint = json.loads(fixture.read_text(encoding="utf-8"))
        proof_map = trace_to_checked_map(hint, SOURCE)
        self.assertEqual([u.step_id for u in scan_proof_map(proof_map).unused_steps], ["s3"])

    def test_a_goal_left_for_a_hypothesis_s_justification_is_held(self) -> None:
        # Mathlib's `have h : 0 < n` (no `:=`) leaves the goal `0 < n`, which only the
        # "why h holds" step relies on. Real exporter output on HaveWithoutValue.lean.
        fixture = Path(__file__).parent / "fixtures" / "have_without_value.trace.json"
        have = json.loads(fixture.read_text(encoding="utf-8"))
        proof_map = trace_to_checked_map(have, SOURCE)
        self.assertEqual(proof_map.steps["s1-why1"].depends_on, ("s2",))
        self.assertEqual(scan_proof_map(proof_map).unused_steps, ())

    def test_trace_whose_goal_nobody_works_on_is_rejected(self) -> None:
        broken = copy.deepcopy(trace())
        broken["steps"] = [s for s in broken["steps"] if s["index"] != 0]
        with self.assertRaisesRegex(LeanImportError, "No step of the proof works on"):
            trace_to_proof_map(broken, SOURCE)


if __name__ == "__main__":
    unittest.main()
