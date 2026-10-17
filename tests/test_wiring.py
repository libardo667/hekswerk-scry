"""The built-in wiring check."""

import unittest

from hekswerk_scry.checker import WiringProblem, check_wiring
from hekswerk_scry.core.enums import CheckKind, ProblemKind, StepStatus
from tests.helpers import example, make_map, make_step


def kinds(problems: tuple[WiringProblem, ...]) -> list[ProblemKind]:
    return [problem.kind for problem in problems]


class TestWiringCheck(unittest.TestCase):
    def test_example_lines_up_and_says_it_is_not_proven(self) -> None:
        report = check_wiring(example())
        self.assertTrue(report.passed)
        self.assertTrue(report.goal_reached)
        for verdict in report.verdicts.values():
            self.assertIs(verdict.status, StepStatus.WIRING_CHECKED)
            self.assertEqual(verdict.status.label, "Wiring checked (not proven)")
        self.assertIn("not proven", report.summary)
        self.assertIs(report.receipt.checked_by, CheckKind.WIRING)
        self.assertEqual(report.receipt.subject_fingerprint, example().fingerprint())

    def test_missing_fact_breaks_the_step_and_everything_after_it(self) -> None:
        proof_map = make_map(
            [make_step("a", "p", ["nowhere"]), make_step("b", "goal", ["p"], ["a"])], "b"
        )
        report = check_wiring(proof_map)
        self.assertFalse(report.passed)
        self.assertFalse(report.goal_reached)
        self.assertEqual(kinds(report.verdicts["a"].problems), [ProblemKind.FACT_NOT_PROVIDED])
        self.assertEqual(kinds(report.verdicts["b"].problems), [ProblemKind.DEPENDENCY_BROKEN])
        self.assertEqual(report.broken_step_ids(), ("a", "b"))

    def test_fact_from_a_step_that_is_not_listed_gets_a_helpful_hint(self) -> None:
        proof_map = make_map([make_step("a", "p"), make_step("b", "goal", ["p"])], "b")
        problem = check_wiring(proof_map).verdicts["b"].problems[0]
        self.assertIs(problem.kind, ProblemKind.FROM_UNLISTED_STEP)
        self.assertIn("Step 'a' proves it", problem.message)

    def test_dependency_on_a_step_that_does_not_exist(self) -> None:
        proof_map = make_map([make_step("a", "goal", depends_on=["ghost"])], "a")
        problem = check_wiring(proof_map).verdicts["a"].problems[0]
        self.assertIs(problem.kind, ProblemKind.UNKNOWN_DEPENDENCY)
        self.assertIn("'ghost'", problem.message)

    def test_an_arrow_whose_fact_is_never_used_is_noted_but_not_a_problem(self) -> None:
        proof_map = make_map([make_step("a", "p"), make_step("b", "goal", [], ["a"])], "b")
        verdict = check_wiring(proof_map).verdicts["b"]
        self.assertIs(verdict.status, StepStatus.WIRING_CHECKED)
        self.assertIn("never uses what it proves", verdict.notes[0])

    def test_a_starting_fact_counts_even_if_a_listed_step_is_broken(self) -> None:
        proof_map = make_map(
            [make_step("a", "s", ["nowhere"]), make_step("b", "goal", ["s"], ["a"])],
            "b",
            starting_facts=["s"],
        )
        report = check_wiring(proof_map)
        self.assertIs(report.verdicts["b"].status, StepStatus.WIRING_CHECKED)
        self.assertTrue(report.goal_reached)
        self.assertFalse(report.passed)  # step 'a' itself is still broken

    def test_goal_step_must_exist_and_prove_the_goal(self) -> None:
        missing = make_map([make_step("a", "p")], "nope", goal="p")
        self.assertEqual(kinds(check_wiring(missing).map_problems), [ProblemKind.GOAL_STEP_MISSING])
        wrong = make_map([make_step("a", "p")], "a", goal="q")
        self.assertEqual(
            kinds(check_wiring(wrong).map_problems), [ProblemKind.GOAL_STEP_PROVES_SOMETHING_ELSE]
        )

    def test_loop_leaves_every_step_not_checked(self) -> None:
        proof_map = make_map(
            [make_step("a", "p", ["q"], ["b"]), make_step("b", "q", ["p"], ["a"])], "a"
        )
        report = check_wiring(proof_map)
        self.assertEqual(kinds(report.map_problems), [ProblemKind.LOOP])
        self.assertFalse(report.passed)
        for verdict in report.verdicts.values():
            self.assertIs(verdict.status, StepStatus.NOT_CHECKED)
            self.assertEqual(verdict.status.label, "Not checked")

    def test_wiring_check_never_produces_lean_checked(self) -> None:
        for proof_map in (example(), make_map([make_step("a", "p", ["x"])], "a")):
            statuses = {v.status for v in check_wiring(proof_map).verdicts.values()}
            self.assertNotIn(StepStatus.LEAN_CHECKED, statuses)


if __name__ == "__main__":
    unittest.main()
