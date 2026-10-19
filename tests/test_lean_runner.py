"""Reading Lean's output and judging whether a theorem is proven.

The fixtures in tests/fixtures/lean_output are real output from Lean v4.10.0-rc2 running
on the bundled example: as written, with one `sorry`, and with a deliberate mistake.
"""

import json
import tempfile
import unittest
from pathlib import Path

from hekswerk_scry.lean.runner import (
    STANDARD_AXIOMS,
    LeanCheck,
    check_file,
    find_axioms,
    judge,
    parse_output,
)
from hekswerk_scry.lean.workspace import LeanWorkspace
from hekswerk_scry.models import Receipt
from hekswerk_scry.models.receipts import LeanRunEvidence

FIXTURES = Path(__file__).parent / "fixtures" / "lean_output"
THEOREM = "shifted_fraction_ne_one"


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestReadingLeanOutput(unittest.TestCase):
    def test_messages_are_read_with_positions(self) -> None:
        messages, other = parse_output(read("passing.jsonl"))
        self.assertEqual(other, ())
        self.assertEqual([m.severity for m in messages], ["warning", "information"])
        self.assertEqual((messages[0].line, messages[0].column), (18, 7))
        self.assertIn("unused variable `sq_nonneg_x`", messages[0].text)

    def test_lines_that_are_not_lean_messages_are_kept_apart(self) -> None:
        # Mathlib's linarith prints debugging lines like this one; they are not errors.
        messages, other = parse_output(read("passing_with_trace_line.jsonl"))
        self.assertEqual(len(other), 1)
        self.assertIn("Linarith", other[0])
        self.assertFalse(any(m.is_error for m in messages))
        self.assertEqual(judge(messages, find_axioms(messages, THEOREM), THEOREM,
                               exit_code=0), ())

    def test_axioms_are_found(self) -> None:
        messages, _ = parse_output(read("passing.jsonl"))
        self.assertEqual(set(find_axioms(messages, THEOREM) or ()), STANDARD_AXIOMS)
        self.assertIsNone(find_axioms(messages, "some_other_theorem"))


class TestJudging(unittest.TestCase):
    def test_passing_proof(self) -> None:
        messages, _ = parse_output(read("passing.jsonl"))
        self.assertEqual(judge(messages, find_axioms(messages, THEOREM), THEOREM,
                               exit_code=0), ())

    def test_sorry_is_never_proven(self) -> None:
        messages, _ = parse_output(read("sorry.jsonl"))
        problems = judge(messages, find_axioms(messages, THEOREM), THEOREM, exit_code=0)
        self.assertEqual(len(problems), 1)
        self.assertIn("uses `sorry`", problems[0])

    def test_sorry_hidden_in_another_file_is_never_proven(self) -> None:
        # A lemma left as `sorry` in another file: Lean warns there, not here, but the
        # theorem's axioms still include sorryAx.
        problems = judge((), ("propext", "sorryAx", "Quot.sound"), THEOREM, exit_code=0)
        self.assertEqual(len(problems), 1)
        self.assertIn("uses `sorry`", problems[0])

    def test_errors_are_reported_without_blaming_sorry(self) -> None:
        # After an error Lean patches the spot with sorry itself; the author wrote none.
        messages, _ = parse_output(read("error.jsonl"))
        problems = judge(messages, find_axioms(messages, THEOREM), THEOREM, exit_code=1)
        self.assertEqual(len(problems), 1)
        self.assertIn("Lean reported 1 error(s). The first, at line 12", problems[0])
        self.assertIn("linarith failed", problems[0])

    def test_extra_axioms_are_never_proven(self) -> None:
        problems = judge((), ("propext", "my_magic_axiom"), THEOREM, exit_code=0)
        self.assertIn("beyond Lean's standard three: my_magic_axiom", problems[0])

    def test_missing_theorem_and_timeout(self) -> None:
        self.assertIn("did not report on a theorem called", judge((), None, THEOREM,
                                                                     exit_code=0)[0])
        self.assertIn("longer than 5 seconds", judge((), None, THEOREM, exit_code=None,
                                                    timed_out=True, timeout=5)[0])

    def test_a_run_that_did_not_end_normally_is_never_proven(self) -> None:
        # Output that would pass, from a process that then failed: a crash need not leave
        # an error message behind.
        messages, _ = parse_output(read("passing.jsonl"))
        axioms = find_axioms(messages, THEOREM)
        for exit_code, says in [(23, "ended with exit code 23"), (-9, "stopped by signal 9"),
                                (None, "ended with exit code None")]:
            with self.subTest(exit_code=exit_code):
                problems = judge(messages, axioms, THEOREM, exit_code=exit_code)
                self.assertEqual(len(problems), 1)
                self.assertIn(says, problems[0])


class TestFreshRuns(unittest.TestCase):
    """The whole fresh-run path, with a stand-in for `lake` that prints Lean's message for a
    finished proof and then ends in different ways. Only the ending varies."""

    MESSAGE = json.dumps({"severity": "information", "pos": {"line": 3, "column": 0},
                          "data": "'t' does not depend on any axioms"})

    def check(self, ending: str, *, prints: str = MESSAGE, timeout: float = 30) -> LeanCheck:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "lean-toolchain").write_text("leanprover/lean4:v4.34.1\n")
            (root / "printed.txt").write_text(prints + "\n")
            lake = root / "lake"
            lake.write_text(f"#!/bin/sh\ncat '{root / 'printed.txt'}'\n{ending}\n")
            lake.chmod(0o700)
            workspace = LeanWorkspace(root=root, lake=lake, exporter=root / "none",
                                      is_scry_project=False)
            source = root / "Claim.lean"
            source.write_text("theorem t : True := trivial\n")
            return check_file(workspace, source, "t", fresh=True, timeout=timeout)

    def test_a_clean_ending_passes(self) -> None:
        checked = self.check("exit 0")
        self.assertTrue(checked.passed, checked.problems)
        self.assertEqual(checked.receipt.lean_run and checked.receipt.lean_run.exit_code, 0)

    def test_a_failed_ending_does_not_pass(self) -> None:
        for ending in ("exit 23", "kill -9 $$"):
            with self.subTest(ending=ending):
                checked = self.check(ending)
                self.assertFalse(checked.passed)
                self.assertFalse(checked.receipt.passed)
                self.assertIn("Lean's run failed", checked.problems[0])
                self.assertTrue(checked.receipt.summary.startswith("Not proven by Lean"))

    def test_running_out_of_time_does_not_pass(self) -> None:
        checked = self.check("sleep 30", timeout=1)
        self.assertFalse(checked.passed)
        self.assertIn("longer than 1 seconds", checked.problems[0])

    def test_output_without_lean_s_report_does_not_pass(self) -> None:
        checked = self.check("exit 0", prints="half a line")
        self.assertFalse(checked.passed)
        self.assertIn("did not report on a theorem called 't'", checked.problems[0])


class TestLeanReceipts(unittest.TestCase):
    def test_a_receipt_from_a_failed_run_cannot_say_passed(self) -> None:
        for exit_code, timed_out in [(23, False), (-9, False), (None, True), (None, False)]:
            run = LeanRunEvidence(("lake", "env", "lean"), exit_code, timed_out, "0" * 64, 1.0)
            with self.subTest(exit_code=exit_code, timed_out=timed_out):
                with self.assertRaisesRegex(ValueError, "ended normally"):
                    Receipt.from_lean_run(run, subject="t", subject_fingerprint="x",
                                          passed=True, summary="Lean-checked")
                # Recording the failure is fine.
                Receipt.from_lean_run(run, subject="t", subject_fingerprint="x",
                                      passed=False, summary="Not proven by Lean")


if __name__ == "__main__":
    unittest.main()
