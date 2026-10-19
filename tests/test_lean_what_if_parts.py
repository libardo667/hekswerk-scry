"""The pieces of Lean What-If tests and Lean step verdicts that don't need Lean itself."""

import unittest
from pathlib import Path

from hekswerk_scry.core.enums import StepStatus
from hekswerk_scry.lean.checks import innermost_step_at, verdicts_from_check
from hekswerk_scry.lean.runner import LeanCheck, find_axioms, judge, parse_output
from hekswerk_scry.lean.source_text import offsets
from hekswerk_scry.lean.what_if import (
    REPLACEMENT,
    distances_from,
    original_position,
    steps_inside,
)
from hekswerk_scry.models import LeanRange, Receipt
from hekswerk_scry.models.receipts import LeanRunEvidence
from tests.test_lean_importer import lean_map

OUTPUT = Path(__file__).parent / "fixtures" / "lean_output"


def lean_check(fixture: str) -> LeanCheck:
    messages, other = parse_output((OUTPUT / fixture).read_text(encoding="utf-8"))
    axioms = find_axioms(messages, "shifted_fraction_ne_one")
    problems = judge(messages, axioms, "shifted_fraction_ne_one", exit_code=0)
    # A stand-in for the evidence of a Lean run: these tests replay recorded Lean output.
    evidence = LeanRunEvidence(("lean", "--json", "Check.lean"), 0, False, "0" * 64, 0.0)
    receipt = Receipt.from_lean_run(
        evidence, subject="test", subject_fingerprint="x", passed=not problems, summary="test"
    )
    return LeanCheck("f.lean", "shifted_fraction_ne_one", not problems, problems, messages,
                     axioms, other, 0.0, receipt)


class TestPositions(unittest.TestCase):
    TEXT = "line one\n  have h : 2 = 2 := by rfl\n  exact h\n"

    def test_offsets_count_characters(self) -> None:
        span = LeanRange(2, 2, 2, 26)
        start, end = offsets(self.TEXT, span)
        self.assertEqual(self.TEXT[start:end], "have h : 2 = 2 := by rfl")

    def test_unicode_columns_are_characters_not_bytes(self) -> None:
        text = "x ≥ 0 ∧ y\n"
        start, end = offsets(text, LeanRange(1, 8, 1, 9))
        self.assertEqual(text[start:end], "y")

    def test_positions_after_the_edit_map_back_to_the_original(self) -> None:
        start, end = offsets(self.TEXT, LeanRange(2, 2, 2, 26))
        edited = self.TEXT[:start] + REPLACEMENT + self.TEXT[end:]
        check = lean_check("error.jsonl")
        message = check.messages[0]
        moved = type(message)(message.severity, 3, 2, None, None, "x")
        self.assertEqual(original_position(self.TEXT, edited, start, end, moved), (3, 2))
        inside = type(message)(message.severity, 2, 4, None, None, "x")
        self.assertEqual(original_position(self.TEXT, edited, start, end, inside), (2, 2))


class TestStepsAndVerdicts(unittest.TestCase):
    def test_innermost_step_wins(self) -> None:
        # Line 12, column 49 is the `linarith` inside `have cube_pos ... (by linarith) 3`.
        self.assertEqual(innermost_step_at(lean_map(), 12, 50), "s2")
        self.assertEqual(innermost_step_at(lean_map(), 12, 4), "s1")
        self.assertIsNone(innermost_step_at(lean_map(), 1, 0))

    def test_removing_a_have_removes_what_is_inside_it(self) -> None:
        span = lean_map().steps["s7"].lean_range
        assert span is not None
        self.assertEqual(steps_inside(lean_map(), span), {"s7", "s7-why1", "s8", "s8-why1", "s9"})

    def test_distances(self) -> None:
        distance = distances_from(lean_map(), "s3")
        self.assertEqual(distance["s3"], 0)
        self.assertEqual(distance["s5"], 1)

    def test_passing_check_marks_every_step_lean_checked(self) -> None:
        report = verdicts_from_check(lean_map(), lean_check("passing.jsonl"))
        self.assertEqual({v.status for v in report.verdicts.values()}, {StepStatus.LEAN_CHECKED})

    def test_failing_check_marks_the_error_and_nothing_else_as_proven(self) -> None:
        report = verdicts_from_check(lean_map(), lean_check("error.jsonl"))
        self.assertIs(report.verdicts["s2"].status, StepStatus.LEAN_REJECTED)
        self.assertIn("linarith failed", report.verdicts["s2"].lean_errors[0])
        others = {v.status for sid, v in report.verdicts.items() if sid != "s2"}
        self.assertEqual(others, {StepStatus.NOT_CHECKED})

    def test_sorry_means_nothing_is_lean_checked(self) -> None:
        report = verdicts_from_check(lean_map(), lean_check("sorry.jsonl"))
        self.assertNotIn(StepStatus.LEAN_CHECKED, {v.status for v in report.verdicts.values()})


if __name__ == "__main__":
    unittest.main()
