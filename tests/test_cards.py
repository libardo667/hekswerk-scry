"""Simplification cards: checking, swapping, staleness, and history."""

import unittest
from dataclasses import replace

from hekswerk_scry.checker import CardRejectedError, apply_card, check_card, check_wiring
from hekswerk_scry.core.enums import CardStatus
from hekswerk_scry.models import ProofMap, ProofStep, SimplificationCard, StepViews
from tests.helpers import KNOT_STEPS, direct_shift_step, example, make_map, make_step


def draft(
    proof_map: ProofMap,
    replacement: list[ProofStep],
    region: tuple[str, ...] = KNOT_STEPS,
) -> SimplificationCard:
    return SimplificationCard.draft(
        proof_map,
        card_id="card",
        title="Test card",
        why="Testing.",
        region_step_ids=region,
        replacement_steps=replacement,
    )


class TestHonestSwap(unittest.TestCase):
    def test_knot_is_swapped_archived_and_recorded(self) -> None:
        proof_map = example()
        card = draft(proof_map, [direct_shift_step()])
        check = check_card(proof_map, card)
        self.assertIs(check.status, CardStatus.READY_TO_SWAP)
        self.assertIn("not proven", check.receipt.summary)

        new_map, receipt = apply_card(proof_map, card)
        self.assertEqual(set(new_map.archived_steps), set(KNOT_STEPS))
        self.assertNotIn("cube-split", new_map.steps)
        self.assertEqual(
            new_map.steps["fraction-below-one"].depends_on,
            ("less-than-shift", "shift-positive-direct"),
        )
        self.assertEqual(len(new_map.history), 1)
        self.assertEqual(new_map.history[0].receipt_id, receipt.receipt_id)
        self.assertEqual(new_map.history[0].added_step_ids, ("shift-positive-direct",))
        self.assertTrue(check_wiring(new_map).passed)

    def test_original_map_is_left_untouched(self) -> None:
        proof_map = example()
        before = proof_map.fingerprint()
        apply_card(proof_map, draft(proof_map, [direct_shift_step()]))
        self.assertEqual(proof_map.fingerprint(), before)

    def test_replacing_a_group_that_contains_the_goal_step_moves_the_goal(self) -> None:
        proof_map = make_map(
            [
                make_step("a", "p", ["s"]),
                make_step("b", "q", ["p"], ["a"]),
                make_step("c", "goal", ["q"], ["b"]),
            ],
            "c",
            ["s"],
        )
        card = draft(proof_map, [make_step("direct", "goal", ["s"])], region=("b", "c"))
        new_map, _ = apply_card(proof_map, card)
        self.assertEqual(new_map.goal_step_id, "direct")
        self.assertTrue(check_wiring(new_map).goal_reached)

    def test_replacement_may_be_several_steps(self) -> None:
        proof_map = example()
        card = draft(
            proof_map,
            [
                make_step("seven-positive", "x + 7 >= 7", ["x >= 0"]),
                make_step("shift-ok", "x + 7 > 0", ["x + 7 >= 7"], ["seven-positive"]),
            ],
        )
        new_map, _ = apply_card(proof_map, card)
        self.assertTrue(check_wiring(new_map).passed)
        self.assertIn("shift-ok", new_map.steps["fraction-below-one"].depends_on)


class TestRejectedCards(unittest.TestCase):
    def assert_rejected(self, card: SimplificationCard, phrase: str) -> None:
        proof_map = example()
        check = check_card(proof_map, card)
        self.assertIs(check.status, CardStatus.REJECTED)
        self.assertTrue(
            any(phrase in problem for problem in check.problems),
            f"Expected a problem mentioning {phrase!r}, got {check.problems}",
        )
        self.assertFalse(check.receipt.passed)
        self.assertIsNone(check.result_map)
        with self.assertRaises(CardRejectedError):
            apply_card(proof_map, card)

    def test_new_assumptions_are_not_allowed(self) -> None:
        card = draft(example(), [make_step("cheat", "x + 7 > 0", ["x > 0"])])
        self.assert_rejected(card, "may not bring in new assumptions")

    def test_replacement_must_still_provide_what_the_rest_needs(self) -> None:
        card = draft(example(), [make_step("wrong", "x + 7 >= 0", ["x >= 0"])])
        self.assert_rejected(card, "never proves it")

    def test_empty_replacement(self) -> None:
        self.assert_rejected(draft(example(), []), "no replacement steps")

    def test_id_clashes(self) -> None:
        self.assert_rejected(draft(example(), [direct_shift_step("less-than-shift")]),
                             "already used by another step")
        self.assert_rejected(draft(example(), [direct_shift_step("cube-split")]),
                             "also the ID of a step being replaced")

    def test_replacement_may_not_depend_on_removed_steps(self) -> None:
        step = make_step("sneaky", "x + 7 > 0", ["x >= 0"], ["cube-split"])
        self.assert_rejected(draft(example(), [step]), "which this card removes")

    def test_ids_retired_by_an_earlier_swap_cannot_be_reused(self) -> None:
        proof_map, _ = apply_card(example(), draft(example(), [direct_shift_step()]))
        card = draft(
            proof_map,
            [direct_shift_step("cube-positive")],
            region=("shift-positive-direct",),
        )
        check = check_card(proof_map, card)
        self.assertIs(check.status, CardStatus.REJECTED)
        self.assertIn("retired by an earlier swap", check.problems[0])

    def test_swap_that_would_break_a_step_outside_the_group_is_rejected(self) -> None:
        # 'reader' uses the in-between result 'p' of the group directly, so it is an output.
        proof_map = make_map(
            [
                make_step("a", "p", ["s"]),
                make_step("b", "q", ["p"], ["a"]),
                make_step("reader", "r", ["p"], ["a"]),
                make_step("end", "goal", ["q", "r"], ["b", "reader"]),
            ],
            "end",
            ["s"],
        )
        card = draft(proof_map, [make_step("direct", "q", ["s"])], region=("a", "b"))
        check = check_card(proof_map, card)
        self.assertIs(check.status, CardStatus.REJECTED)
        self.assertIn("needs 'p'", check.problems[0])


class TestStaleCards(unittest.TestCase):
    def test_card_goes_stale_when_a_replaced_step_changes(self) -> None:
        proof_map = example()
        card = draft(proof_map, [direct_shift_step()])
        edited_step = replace(
            proof_map.steps["cube-split"], views=StepViews(plain_english="Rewritten.")
        )
        edited = proof_map.with_steps({**proof_map.steps, "cube-split": edited_step})
        check = check_card(edited, card)
        self.assertIs(check.status, CardStatus.STALE)
        self.assertIn("'cube-split' has changed", check.problems[0])
        with self.assertRaisesRegex(CardRejectedError, "Stale"):
            apply_card(edited, card)

    def test_card_cannot_be_applied_twice(self) -> None:
        proof_map = example()
        card = draft(proof_map, [direct_shift_step()])
        new_map, _ = apply_card(proof_map, card)
        self.assertIs(check_card(new_map, card).status, CardStatus.STALE)

    def test_apply_rechecks_even_after_a_passing_check(self) -> None:
        # Checked and ready on one version of the map...
        proof_map = example()
        card = draft(proof_map, [direct_shift_step()])
        self.assertIs(check_card(proof_map, card).status, CardStatus.READY_TO_SWAP)
        # ...then the starting fact the replacement relies on is removed elsewhere.
        changed = replace(proof_map, starting_facts=())
        with self.assertRaises(CardRejectedError):
            apply_card(changed, card)


if __name__ == "__main__":
    unittest.main()
