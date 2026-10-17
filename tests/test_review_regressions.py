"""The nine ways the first draft's checker could be fooled, kept as permanent tests.

Each test is named after the case in the Checkpoint 1 review (P1 to P9). See
docs/decisions/0001-only-lean-says-proven.md for the background. Some cases can't be
fixed by the wiring check (it doesn't read math), so their tests pin down the honest
behaviour instead: the check makes no claim about the math, and says so.
"""

import dataclasses
import inspect
import unittest
from dataclasses import replace

from hekswerk_scry.checker import (
    CardRejectedError,
    WiringReport,
    apply_card,
    check_card,
    check_wiring,
    run_what_if,
)
from hekswerk_scry.core.enums import CardStatus, CheckKind, ProblemKind, StepStatus, WhatIfKind
from hekswerk_scry.models import ProofMap, SimplificationCard, StepContract, StepViews, WhatIfChange
from tests.helpers import KNOT_STEPS, direct_shift_step, example, make_map, make_step


def verdict_outline(report: WiringReport) -> dict[str, tuple[StepStatus, tuple[str, ...]]]:
    """Everything the wiring check concluded, without fingerprints."""
    return {
        step_id: (verdict.status, tuple(p.message for p in verdict.problems))
        for step_id, verdict in report.verdicts.items()
    }


def with_views(proof_map: ProofMap, step_id: str, views: StepViews) -> ProofMap:
    step = replace(proof_map.steps[step_id], views=views)
    return proof_map.with_steps({**proof_map.steps, step_id: step})


class TestReviewRegressions(unittest.TestCase):
    def test_p1_a_proof_that_assumes_its_own_conclusion_is_caught(self) -> None:
        proof_map = make_map(
            [
                make_step(
                    "done",
                    "riemann_hypothesis",
                    ["riemann_hypothesis"],
                    views=StepViews(code="sorry"),
                )
            ],
            "done",
            starting_facts=["riemann_hypothesis"],
        )
        report = check_wiring(proof_map)
        self.assertFalse(report.passed)
        self.assertIn(ProblemKind.GOAL_IS_A_STARTING_FACT, [p.kind for p in report.map_problems])
        self.assertEqual(
            [p.kind for p in report.verdicts["done"].problems], [ProblemKind.USES_OWN_CONCLUSION]
        )

    def test_p1_a_conclusion_from_nowhere_is_labelled_not_proven(self) -> None:
        # The wiring check can't see that `sorry` proves nothing. It must not claim more.
        proof_map = make_map(
            [make_step("done", "riemann_hypothesis", views=StepViews(code="sorry"))], "done"
        )
        report = check_wiring(proof_map)
        self.assertIs(report.verdicts["done"].status, StepStatus.WIRING_CHECKED)
        self.assertEqual(report.verdicts["done"].status.label, "Wiring checked (not proven)")
        self.assertIn("nothing here is proven yet", report.summary)

    def test_p2_nonsense_math_changes_nothing_and_is_never_called_proven(self) -> None:
        nonsense = with_views(
            example(), "cube-split", StepViews(math="2 + 2 = 5", code="exact nonsense_lemma")
        )
        report = check_wiring(nonsense)
        self.assertEqual(verdict_outline(report), verdict_outline(check_wiring(example())))
        self.assertNotIn(StepStatus.LEAN_CHECKED, {v.status for v in report.verdicts.values()})
        self.assertIn("does not read the math or the code", report.summary)

    def test_p3_a_step_cannot_grant_itself_a_safety_condition(self) -> None:
        # There is no separate "restrictions" list any more: a condition is a fact, and a
        # fact must come from a starting fact or from a step that is listed.
        self.assertEqual(
            [f.name for f in dataclasses.fields(StepContract)], ["assumes", "proves"]
        )
        report = run_what_if(example(), WhatIfChange(WhatIfKind.REMOVE_STEP, "shift-positive"))
        self.assertEqual(report.broken_steps[0].step_id, "fraction-below-one")
        self.assertIn("x + 7 > 0", report.broken_steps[0].reasons[0])
        self_granting = make_map([make_step("a", "x + 7 > 0", ["x + 7 > 0"])], "a")
        self.assertFalse(check_wiring(self_granting).passed)

    def test_p3_the_original_demo_question_is_answered_honestly(self) -> None:
        # The first draft told users the "+7" guard was "redundant search noise".
        report = run_what_if(example(), WhatIfChange(WhatIfKind.REMOVE_STEP, "shift-positive"))
        self.assertFalse(report.goal_reached_after)
        self.assertNotIn("noise", report.headline + report.explanation)

    def test_p4_division_is_not_judged_by_pattern_matching(self) -> None:
        unsafe = with_views(
            example(), "fraction-below-one", StepViews(math="r = drift / vortex_core")
        )
        self.assertEqual(
            verdict_outline(check_wiring(unsafe)), verdict_outline(check_wiring(example()))
        )

    def test_p5_no_substring_guessing_about_formulas(self) -> None:
        guessy = with_views(example(), "fraction-below-one", StepViews(math="r = drift / (core)"))
        self.assertEqual(
            verdict_outline(check_wiring(guessy)), verdict_outline(check_wiring(example()))
        )
        # Facts are compared exactly (after tidying spaces), never by substring.
        proof_map = make_map(
            [make_step("a", "vortex_core + 7 > 0"), make_step("b", "goal", ["core > 0"], ["a"])],
            "b",
        )
        self.assertFalse(check_wiring(proof_map).passed)

    def test_p6_the_checker_makes_no_claims_about_english_versus_code(self) -> None:
        reworded = with_views(
            example(),
            "cube-positive",
            StepViews(plain_english="We use the usual energy dissipation estimate.",
                      code="pow_pos (by linarith) 3  -- energy"),
        )
        self.assertEqual(
            verdict_outline(check_wiring(reworded)), verdict_outline(check_wiring(example()))
        )
        self.assertFalse(any("mismatch" in kind.value for kind in ProblemKind))

    def test_p7_a_card_goes_stale_when_its_steps_are_edited(self) -> None:
        proof_map = example()
        card = SimplificationCard.draft(
            proof_map, card_id="c", title="t", why="w",
            region_step_ids=KNOT_STEPS, replacement_steps=[direct_shift_step()],
        )
        edited = with_views(proof_map, "square-positive", StepViews(math="totally different"))
        self.assertIs(check_card(edited, card).status, CardStatus.STALE)
        with self.assertRaises(CardRejectedError):
            apply_card(edited, card)

    def test_p8_a_card_cannot_declare_its_own_contract(self) -> None:
        field_names = {f.name for f in dataclasses.fields(SimplificationCard)}
        self.assertNotIn("expected_contract", field_names)
        card = SimplificationCard.draft(
            example(), card_id="c", title="t", why="w", region_step_ids=KNOT_STEPS,
            replacement_steps=[make_step("whatever", "anything at all", ["x >= 0"])],
        )
        self.assertIs(check_card(example(), card).status, CardStatus.REJECTED)

    def test_p9_receipts_cannot_unlock_a_swap_or_pretend_to_be_lean(self) -> None:
        self.assertEqual([kind.value for kind in CheckKind], ["wiring"])
        self.assertEqual(list(inspect.signature(apply_card).parameters), ["proof_map", "card"])
        # A check that passed earlier counts for nothing once the map has changed.
        proof_map = example()
        card = SimplificationCard.draft(
            proof_map, card_id="c", title="t", why="w",
            region_step_ids=KNOT_STEPS, replacement_steps=[direct_shift_step()],
        )
        self.assertTrue(check_card(proof_map, card).receipt.passed)
        with self.assertRaises(CardRejectedError):
            apply_card(replace(proof_map, starting_facts=()), card)


if __name__ == "__main__":
    unittest.main()
