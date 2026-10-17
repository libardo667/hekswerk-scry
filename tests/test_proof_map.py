"""ProofMap structure: tidy facts, step ordering, loops, and fingerprints."""

import unittest
from dataclasses import replace

from hekswerk_scry.core.enums import ViewKind
from hekswerk_scry.models import DependencyLoopError, ProofStep, StepContract, StepViews
from tests.helpers import example, make_map, make_step


class TestFacts(unittest.TestCase):
    def test_stray_spaces_do_not_create_a_different_fact(self) -> None:
        # The first draft depended on a copied typo: " strictly_positive..." with a leading space.
        contract = StepContract(assumes=("  x + 7   > 0 ",), proves=" y > 0")
        self.assertEqual(contract.assumes, ("x + 7 > 0",))
        self.assertEqual(contract.proves, "y > 0")

    def test_repeated_assumptions_are_kept_once(self) -> None:
        contract = StepContract(assumes=("a", "a ", "b"), proves="c")
        self.assertEqual(contract.assumes, ("a", "b"))

    def test_empty_facts_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must prove something"):
            StepContract(assumes=(), proves="   ")
        with self.assertRaisesRegex(ValueError, "empty fact"):
            StepContract(assumes=("ok", " "), proves="c")

    def test_step_ids_may_not_contain_spaces(self) -> None:
        with self.assertRaisesRegex(ValueError, "no spaces"):
            ProofStep("two words", "t", StepContract((), "p"))

    def test_map_rejects_steps_stored_under_the_wrong_id(self) -> None:
        step = make_step("a", "p")
        with self.assertRaisesRegex(ValueError, "must match"):
            replace(make_map([step], "a"), steps={"b": step})


class TestOrdering(unittest.TestCase):
    def test_every_step_comes_after_the_steps_it_depends_on(self) -> None:
        proof_map = example()
        order = proof_map.topological_order()
        position = {step_id: index for index, step_id in enumerate(order)}
        for step in proof_map.steps.values():
            for dep in step.depends_on:
                self.assertLess(position[dep], position[step.step_id])

    def test_order_is_the_same_every_time(self) -> None:
        self.assertEqual(example().topological_order(), example().topological_order())

    def test_loop_is_reported_in_plain_english(self) -> None:
        proof_map = make_map(
            [make_step("a", "p", ["q"], ["b"]), make_step("b", "q", ["p"], ["a"])], "a"
        )
        with self.assertRaises(DependencyLoopError) as caught:
            proof_map.topological_order()
        self.assertEqual(caught.exception.step_ids, ("a", "b"))
        self.assertIn("depend on each other in a circle", str(caught.exception))

    def test_unknown_dependencies_do_not_stop_ordering(self) -> None:
        proof_map = make_map([make_step("a", "p", depends_on=["ghost"])], "a")
        self.assertEqual(proof_map.topological_order(), ("a",))

    def test_ancestors_and_descendants(self) -> None:
        proof_map = example()
        self.assertEqual(
            proof_map.ancestors_of("fraction-below-one"),
            {"less-than-shift", "shift-positive", "cube-positive", "cube-split", "square-positive"},
        )
        self.assertEqual(
            proof_map.descendants_of("cube-split"),
            {"shift-positive", "fraction-below-one", "fraction-not-one"},
        )


class TestViewsAndFingerprints(unittest.TestCase):
    def test_a_step_can_have_any_mix_of_views(self) -> None:
        self.assertEqual(StepViews(code="exact h").available_kinds(), (ViewKind.CODE,))
        self.assertEqual(StepViews(plain_english="  ").available_kinds(), ())
        self.assertEqual(
            StepViews(plain_english="a", math="b", code="c").available_kinds(),
            (ViewKind.PLAIN_ENGLISH, ViewKind.MATH, ViewKind.CODE),
        )

    def test_fingerprint_changes_with_any_content_change(self) -> None:
        proof_map = example()
        step = proof_map.steps["cube-split"]
        changed_views = replace(step, views=StepViews(code="by simp"))
        changed_title = replace(step, title="Something else")
        base = proof_map.fingerprint()
        self.assertNotEqual(base, proof_map.with_steps(
            {**proof_map.steps, "cube-split": changed_views}).fingerprint())
        self.assertNotEqual(base, proof_map.with_steps(
            {**proof_map.steps, "cube-split": changed_title}).fingerprint())
        self.assertEqual(base, example().fingerprint())


if __name__ == "__main__":
    unittest.main()
