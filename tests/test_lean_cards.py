"""Finding a fact's proof in a Lean file and splicing new tactics in (no Lean needed).

Uses the real exporter trace of lean/Examples/ShiftedFraction.lean and the file itself.
The spliced files are compared in full against the expected text: the artifact is the
test, not a fragment of it.
"""

import json
import random
import unittest
from pathlib import Path

from hekswerk_scry.checker.regions import proof_of
from hekswerk_scry.lean.cards import LeanRegionError, find_region, splice
from hekswerk_scry.lean.importer import trace_to_checked_map
from hekswerk_scry.models import LeanSource, ProofMap
from tests.helpers import make_map, make_step
from tests.test_lean_importer import lean_map

EXAMPLE = Path(__file__).parents[1] / "lean" / "Examples" / "ShiftedFraction.lean"
HEADER, _, _ = EXAMPLE.read_text(encoding="utf-8").partition("theorem")
# The theorem's statement line, exactly as in the file (it is never changed by a swap).
STATEMENT = "theorem" + EXAMPLE.read_text(encoding="utf-8").partition("theorem")[2].split(
    "\n"
)[0] + "\n"


FIXTURES = Path(__file__).parent / "fixtures"


def text() -> str:
    return EXAMPLE.read_text(encoding="utf-8")


def unused_hint_map() -> ProofMap:
    """A `linarith` given a hint (`by norm_num`) that the finished proof never uses."""
    trace = json.loads((FIXTURES / "unused_hint.trace.json").read_text(encoding="utf-8"))
    return trace_to_checked_map(trace, LeanSource("UnusedHint.lean", "unused_hint", "0" * 64))


def unused_hint_text() -> str:
    return (FIXTURES / "lean" / "UnusedHint.lean").read_text(encoding="utf-8")


class TestProofOf(unittest.TestCase):
    def test_invariant_nothing_live_outside_uses_anything_inside_but_the_fact(self) -> None:
        # For every step of many maps, including maps with dead ends (steps that lead
        # nowhere): every step a group member feeds is in the group, unless it is the
        # fact's own step or a dead end. And every member is an earlier step of the fact.
        maps: list[ProofMap] = [lean_map(), unused_hint_map()]
        rng = random.Random(7)
        for _ in range(40):
            steps = []
            for i in range(14):
                deps = rng.sample([f"n{j}" for j in range(i)], k=min(i, rng.randint(0, 3)))
                steps.append(make_step(f"n{i}", f"f{i}", [f"f{d[1:]}" for d in deps], deps))
            maps.append(make_map(steps, f"n{rng.randint(8, 13)}"))
        for proof_map in maps:
            children = proof_map.children()
            goal = proof_map.goal_step_id
            to_goal = proof_map.ancestors_of(goal) | {goal}
            for step_id in proof_map.steps:
                group = set(proof_of(proof_map, step_id))
                live = to_goal | proof_map.ancestors_of(step_id) | {step_id}
                self.assertIn(step_id, group)
                for member in group - {step_id}:
                    self.assertIn(member, proof_map.ancestors_of(step_id))
                    live_users = {c for c in children[member] if c in live}
                    self.assertTrue(live_users, (step_id, member))
                    self.assertTrue(live_users <= group, (step_id, member))

    def test_maximal_nothing_that_could_join_is_left_out(self) -> None:
        for proof_map in (lean_map(), unused_hint_map()):
            children = proof_map.children()
            goal = proof_map.goal_step_id
            to_goal = proof_map.ancestors_of(goal) | {goal}
            for step_id in proof_map.steps:
                group = set(proof_of(proof_map, step_id))
                live = to_goal | proof_map.ancestors_of(step_id) | {step_id}
                for other in proof_map.ancestors_of(step_id) - group:
                    users = {c for c in children[other] if c in live}
                    self.assertFalse(users and users <= group, (step_id, other))

    def test_a_dead_end_does_not_keep_its_inputs_out(self) -> None:
        # p feeds q (on the way to the goal) and also d, which leads nowhere.
        proof_map = make_map(
            [
                make_step("p", "fp"),
                make_step("q", "fq", ["fp"], ["p"]),
                make_step("d", "fd", ["fp"], ["p"]),
                make_step("goal", "fg", ["fq"], ["q"]),
            ],
            "goal",
        )
        self.assertEqual(set(proof_of(proof_map, "q")), {"p", "q"})

    def test_the_cube_detour_is_the_proof_of_shift_pos(self) -> None:
        self.assertEqual(
            set(proof_of(lean_map(), "s7-why1")),
            {"s7-why1", "s8-why1", "s8", "s9", "s1-why1", "s2", "s3-why1", "s4", "s5-why1", "s6"},
        )


class TestFindRegion(unittest.TestCase):
    def test_reproving_a_lemma_removes_the_lines_that_only_fed_it(self) -> None:
        region = find_region(lean_map(), text(), "s7-why1")
        self.assertTrue(region.replaces_lemma_value)
        self.assertEqual((region.anchor.start_line, region.anchor.end_line), (15, 17))
        self.assertEqual([s.start_line for s in region.removed_spans], [12, 13, 14])
        self.assertTrue({"s1", "s3", "s5"} <= set(region.removed_step_ids))
        self.assertNotIn("s7", region.removed_step_ids)  # the `have shift_pos` line stays

    def test_a_nested_tactic_is_its_own_small_region(self) -> None:
        region = find_region(lean_map(), text(), "s2")
        self.assertEqual(region.removed_step_ids, ("s2",))
        self.assertEqual(region.removed_spans, ())

    def test_dead_code_inside_the_cut_goes_with_it(self) -> None:
        # The hint (s3) is in no fact's proof, but its code sits inside h's proof.
        region = find_region(unused_hint_map(), unused_hint_text(), "s1-why1")
        self.assertEqual(set(region.removed_step_ids), {"s1-why1", "s2", "s3"})
        spliced = splice(unused_hint_text(), region, "linarith")
        self.assertIn("  have h : 0 < x + 1 := by\n    linarith\n  exact h\n", spliced.text)

    def test_unused_lemmas_of_removed_steps_go_with_them(self) -> None:
        # Re-proving the whole theorem removes every step, including the unused lemma
        # sq_nonneg_x whose "why" step has no code of its own.
        region = find_region(lean_map(), text(), "s1")
        self.assertEqual(set(region.removed_step_ids), set(lean_map().steps))

    def test_ids_that_do_not_exist_and_maps_without_lean(self) -> None:
        with self.assertRaisesRegex(LeanRegionError, "no step 'ghost'"):
            find_region(lean_map(), text(), "ghost")
        with self.assertRaisesRegex(LeanRegionError, "not made from a Lean file"):
            find_region(make_map([make_step("a", "p")], "a"), text(), "a")


class TestSplice(unittest.TestCase):
    def test_reproving_a_lemma_gives_exactly_this_file(self) -> None:
        spliced = splice(text(), find_region(lean_map(), text(), "s7-why1"), "linarith")
        expected = HEADER + STATEMENT + (
            "  have shift_pos : x + 7 > 0 := by\n"
            "    linarith\n"
            "  have sq_nonneg_x : x ^ 2 ≥ 0 := sq_nonneg x\n"
            "  have lt_shift : x < x + 7 := by linarith\n"
            "  have below_one : x / (x + 7) < 1 := (div_lt_one shift_pos).mpr lt_shift\n"
            "  exact ne_of_lt below_one\n"
        )
        self.assertEqual(spliced.text, expected)
        self.assertEqual((spliced.first_line, spliced.last_line), (13, 13))

    def test_finishing_a_goal_differently_gives_exactly_this_file(self) -> None:
        replacement = """
            -- x + 7 is positive and bigger than x, so the fraction is below 1.
            have h : x / (x + 7) < 1 := by
              rw [div_lt_one (by linarith)]
              linarith
            exact ne_of_lt h
        """
        spliced = splice(text(), find_region(lean_map(), text(), "s13"), replacement)
        expected = HEADER + STATEMENT + (
            "  have sq_nonneg_x : x ^ 2 ≥ 0 := sq_nonneg x\n"
            "  -- x + 7 is positive and bigger than x, so the fraction is below 1.\n"
            "  have h : x / (x + 7) < 1 := by\n"
            "    rw [div_lt_one (by linarith)]\n"
            "    linarith\n"
            "  exact ne_of_lt h\n"
        )
        self.assertEqual(spliced.text, expected)
        self.assertEqual((spliced.first_line, spliced.last_line), (13, 17))

    def test_replacing_a_nested_tactic_keeps_the_rest_of_its_line(self) -> None:
        spliced = splice(text(), find_region(lean_map(), text(), "s2"), "positivity")
        self.assertIn(
            "  have cube_pos : (x + 7) ^ 3 > 0 := pow_pos (by positivity) 3\n", spliced.text
        )
        self.assertEqual(len(spliced.text.splitlines()), len(text().splitlines()))

    def test_every_new_line_is_indented_inside_the_proof(self) -> None:
        # Text that tries to escape the proof (to declare an axiom, say) stays inside it.
        sneaky = "linarith\naxiom cheat : False"
        spliced = splice(text(), find_region(lean_map(), text(), "s7-why1"), sneaky)
        lines = spliced.text.splitlines()[spliced.first_line - 1 : spliced.last_line]
        self.assertEqual(lines, ["    linarith", "    axiom cheat : False"])

    def test_empty_replacement_is_refused(self) -> None:
        with self.assertRaisesRegex(LeanRegionError, "empty"):
            splice(text(), find_region(lean_map(), text(), "s7-why1"), "  \n \n")


if __name__ == "__main__":
    unittest.main()
