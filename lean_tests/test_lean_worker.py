"""The kept-running Lean must judge every file exactly as a fresh `lean` run does.

Each file is checked twice, once in a new `lean` process and once in the kept-running
one, in the order given, and the two results (verdict, problems, and every message) must
be identical. Some files only make sense in sequence: they try to use something an
earlier file declared or an option it set, which must not carry over.
"""

import shutil
import time
import unittest
from pathlib import Path

from hekswerk_scry.lean.runner import LeanCheck, check_file
from hekswerk_scry.lean.worker import close_all
from hekswerk_scry.lean.workspace import LeanWorkspace, find_workspace

REPOSITORY = Path(__file__).parents[1]
MATHLIB = "import Mathlib.Tactic\n\n"

# (name, theorem, file text, whether Lean should accept it)
FILES: list[tuple[str, str, str, bool]] = [
    ("Proven", "p", MATHLIB + "theorem p (x : ℕ) (h : 2 < x) : 0 < x := by omega\n", True),
    ("Broken", "p", MATHLIB + "theorem p (x : ℕ) : 0 < x := by omega\n", False),
    ("Sorry", "p", MATHLIB + "theorem p (x : ℕ) : 0 < x := by sorry\n", False),
    ("ExtraAxiom", "p", MATHLIB + "axiom cheat : False\n\ntheorem p : 1 = 2 := cheat.elim\n",
     False),
    ("Missing", "q", MATHLIB + "theorem p : True := trivial\n", False),
    # Declares a helper and turns an option on; neither may be visible to the next files.
    ("Declares", "p", MATHLIB + "set_option autoImplicit true\n\n"
     "theorem leaked_helper : 1 + 1 = 2 := rfl\n\n"
     "theorem p : 1 + 1 = 2 := leaked_helper\n", True),
    ("UsesHelper", "p", MATHLIB + "theorem p : 1 + 1 = 2 := leaked_helper\n", False),
    ("UsesOption", "p", MATHLIB + "theorem p (h : a = a) : a = a := h\n", False),
    # Different imports: a second loaded environment, then back to the first.
    ("NoMathlib", "p", "theorem p : 2 + 2 = 4 := rfl\n", True),
    ("Prints", "p", MATHLIB + '#eval IO.println "hello from the file"\n\n'
     "theorem p : True := trivial\n", True),
    ("ProvenAgain", "p", MATHLIB + "theorem p (x : ℕ) (h : 2 < x) : 0 < x := by omega\n", True),
]


def outcome(check: LeanCheck) -> tuple[object, ...]:
    return (check.passed, check.problems, check.messages, check.axioms)


class TestKeptRunningLeanMatchesFreshLean(unittest.TestCase):
    workspace: LeanWorkspace
    folder: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.workspace = find_workspace(REPOSITORY)
        cls.folder = cls.workspace.root / ".scry-runs" / "worker-test"
        shutil.rmtree(cls.folder, ignore_errors=True)
        cls.folder.mkdir(parents=True)

    @classmethod
    def tearDownClass(cls) -> None:
        close_all()

    def test_every_file_gets_the_same_judgment_both_ways(self) -> None:
        close_all()
        kept_seconds: list[float] = []
        for name, theorem, text, accepted in FILES:
            path = self.folder / f"{name}.lean"
            path.write_text(text, encoding="utf-8")
            fresh = check_file(self.workspace, path, theorem, fresh=True)
            kept = check_file(self.workspace, path, theorem)
            kept_seconds.append(kept.seconds)
            with self.subTest(name):
                self.assertEqual(fresh.passed, accepted, fresh.problems)
                self.assertEqual(outcome(kept), outcome(fresh))
                assert kept.receipt.lean_run and fresh.receipt.lean_run
                self.assertIn("--serve", kept.receipt.lean_run.command)
                self.assertNotIn("--serve", fresh.receipt.lean_run.command)
        # The point of it: once the imports are loaded, a check takes seconds.
        self.assertLess(kept_seconds[-1], 10, kept_seconds)

    def test_a_check_that_runs_out_of_time_does_not_break_the_next(self) -> None:
        path = self.folder / "Slow.lean"
        # A program that never stops, run while Lean reads the file.
        path.write_text(MATHLIB + "partial def forever (n : Nat) : IO Nat := forever (n + 1)\n\n"
                        "#eval forever 0\n\ntheorem p : True := trivial\n", encoding="utf-8")
        started = time.monotonic()
        slow = check_file(self.workspace, path, "p", timeout=3)
        self.assertFalse(slow.passed)
        self.assertIn("longer than 3 seconds", slow.problems[0])
        self.assertLess(time.monotonic() - started, 30)
        fine = self.folder / "AfterSlow.lean"
        fine.write_text(MATHLIB + "theorem p : True := trivial\n", encoding="utf-8")
        self.assertTrue(check_file(self.workspace, fine, "p").passed)


if __name__ == "__main__":
    unittest.main()
