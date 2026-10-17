"""Reading Lean's output and judging whether a theorem is proven.

The fixtures in tests/fixtures/lean_output are real output from Lean v4.10.0-rc2 running
on the bundled example: as written, with one `sorry`, and with a deliberate mistake.
"""

import unittest
from pathlib import Path

from hekswerk_scry.lean.runner import STANDARD_AXIOMS, find_axioms, judge, parse_output

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
        self.assertEqual(judge(messages, find_axioms(messages, THEOREM), THEOREM), ())

    def test_axioms_are_found(self) -> None:
        messages, _ = parse_output(read("passing.jsonl"))
        self.assertEqual(set(find_axioms(messages, THEOREM) or ()), STANDARD_AXIOMS)
        self.assertIsNone(find_axioms(messages, "some_other_theorem"))


class TestJudging(unittest.TestCase):
    def test_passing_proof(self) -> None:
        messages, _ = parse_output(read("passing.jsonl"))
        self.assertEqual(judge(messages, find_axioms(messages, THEOREM), THEOREM), ())

    def test_sorry_is_never_proven(self) -> None:
        messages, _ = parse_output(read("sorry.jsonl"))
        problems = judge(messages, find_axioms(messages, THEOREM), THEOREM)
        self.assertEqual(len(problems), 1)
        self.assertIn("uses `sorry`", problems[0])

    def test_sorry_hidden_in_another_file_is_never_proven(self) -> None:
        # A lemma left as `sorry` in another file: Lean warns there, not here, but the
        # theorem's axioms still include sorryAx.
        problems = judge((), ("propext", "sorryAx", "Quot.sound"), THEOREM)
        self.assertEqual(len(problems), 1)
        self.assertIn("uses `sorry`", problems[0])

    def test_errors_are_reported_without_blaming_sorry(self) -> None:
        # After an error Lean patches the spot with sorry itself; the author wrote none.
        messages, _ = parse_output(read("error.jsonl"))
        problems = judge(messages, find_axioms(messages, THEOREM), THEOREM)
        self.assertEqual(len(problems), 1)
        self.assertIn("Lean reported 1 error(s). The first, at line 12", problems[0])
        self.assertIn("linarith failed", problems[0])

    def test_extra_axioms_are_never_proven(self) -> None:
        problems = judge((), ("propext", "my_magic_axiom"), THEOREM)
        self.assertIn("beyond Lean's standard three: my_magic_axiom", problems[0])

    def test_missing_theorem_and_timeout(self) -> None:
        self.assertIn("did not report on a theorem called", judge((), None, THEOREM)[0])
        self.assertIn("longer than 5 seconds", judge((), None, THEOREM, timed_out=True,
                                                    timeout=5)[0])


if __name__ == "__main__":
    unittest.main()
