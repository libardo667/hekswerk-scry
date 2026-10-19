"""What an audit is told about the proof of the statement it audits (no model, no real Lean).

`openai/math` says each comparator challenge's solution module proves it. That is the
repository's claim; the helper is told only what Scry checked here. Lean is stood in for by
a small program that answers like Lean, so the whole checking path runs.
"""

import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hekswerk_scry.ai import audit
from hekswerk_scry.ai.audit import ProofStatus, audit_challenge, check_solution
from hekswerk_scry.lean import openai_math
from hekswerk_scry.lean.openai_math import Challenge
from hekswerk_scry.lean.statement import report_from_json
from hekswerk_scry.lean.workspace import LeanWorkspace
from tests.test_statement import EVIDENCE, raw

THEOREM = "OAI.TruffetV4Counterexample.finite_execution_not_optimal"
SAYS_PROVED = "Lean, run here, accepts"


class SolutionCase(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root / "lean-toolchain").write_text("leanprover/lean4:v4.34.1\n")
        self.statement = self.root / "ComparatorChallenges" / "Truffet.lean"
        self.statement.parent.mkdir()
        self.statement.write_text("theorem t : True := sorry\n")
        self.solution = self.root / "OAI" / "Solution.lean"

    def workspace(self, axioms: str | None) -> LeanWorkspace:
        """A stand-in for Lean that reports `THEOREM`'s axioms (None: says nothing)."""
        if axioms is None:
            printed = ""
        elif axioms:
            printed = json.dumps({"severity": "information", "pos": {"line": 3, "column": 0},
                                  "data": f"'{THEOREM}' depends on axioms: [{axioms}]"})
        else:
            printed = json.dumps({"severity": "information", "pos": {"line": 3, "column": 0},
                                  "data": f"'{THEOREM}' does not depend on any axioms"})
        (self.root / "printed.txt").write_text(printed + "\n")
        lake = self.root / "lake"
        lake.write_text(f"#!/bin/sh\ncat '{self.root / 'printed.txt'}'\nexit 0\n")
        lake.chmod(0o700)
        return LeanWorkspace(root=self.root, lake=lake, exporter=self.root / "none",
                             is_scry_project=False)

    def challenge(self) -> Challenge:
        return Challenge("Truffet", self.statement, "OAI.Solution", self.solution,
                         (THEOREM,), ("propext", "Classical.choice", "Quot.sound"))


class TestCheckingTheSolution(SolutionCase):
    def test_a_solution_lean_accepts_here_is_reported_with_what_was_not_checked(self) -> None:
        self.solution.parent.mkdir()
        self.solution.write_text("theorem x : True := trivial\n")
        status = check_solution(self.workspace("propext, Quot.sound"), self.challenge())
        self.assertTrue(status.checked)
        self.assertIn(SAYS_PROVED, status.text)
        self.assertIn("has not checked that the solution's statement is exactly this file's",
                      status.text)
        self.assertEqual(len(status.receipts), 1)
        checked = (self.root / audit.SOLUTION_CHECKS / "Truffet.lean").read_text()
        self.assertEqual(checked, "import OAI.Solution\n")

    def test_a_solution_resting_on_sorry_is_not_a_proof(self) -> None:
        self.solution.parent.mkdir()
        self.solution.write_text("theorem x : True := sorry\n")
        status = check_solution(self.workspace("propext, sorryAx"), self.challenge())
        self.assertFalse(status.checked)
        self.assertNotIn(SAYS_PROVED, status.text)
        self.assertIn("did not accept", status.text)
        self.assertIn("uses `sorry`", status.text)
        self.assertIn("Treat the statement as unproved", status.text)

    def test_lean_saying_nothing_is_not_a_proof(self) -> None:
        self.solution.parent.mkdir()
        self.solution.write_text("theorem x : True := trivial\n")
        status = check_solution(self.workspace(None), self.challenge())
        self.assertFalse(status.checked)
        self.assertIn("did not report on a theorem", status.text)

    def test_a_missing_solution_is_not_checked_and_lean_is_not_run(self) -> None:
        with mock.patch.object(audit, "check_file") as check:
            status = check_solution(self.workspace(""), self.challenge())
        check.assert_not_called()
        self.assertFalse(status.checked)
        self.assertIn("isn't in this checkout", status.text)
        self.assertNotIn(SAYS_PROVED, status.text)


class TestWhatTheHelperIsTold(SolutionCase):
    def prompt_for(self, status: ProofStatus | None = None) -> tuple[str, object]:
        """The instructions `audit_challenge` gives the helper, and the status it records.
        With `status`, the solution check is replaced by that answer."""
        ws = self.workspace("propext")
        report = report_from_json(raw("truffet_challenge"), "Truffet.lean", EVIDENCE)
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(openai_math, "challenge",
                                                  return_value=self.challenge()))
            stack.enter_context(mock.patch.object(audit, "workspace_for_file", return_value=ws))
            stack.enter_context(mock.patch.object(audit, "paper_files_for",
                                                  return_value=((), [])))
            stack.enter_context(mock.patch.object(audit, "read_statement", return_value=report))
            if status is not None:
                stack.enter_context(mock.patch.object(audit, "check_solution",
                                                      return_value=status))
            run = stack.enter_context(mock.patch.object(audit, "run_audit"))
            audit_challenge(mock.Mock(), "Truffet")
        return run.call_args.args[2], run.call_args.args[7]

    def test_an_unchecked_proof_is_never_described_as_checked(self) -> None:
        # No solution file: Scry checked nothing, and the helper is told exactly that.
        prompt, status = self.prompt_for()
        self.assertNotIn("checked a proof", prompt)
        self.assertNotIn(SAYS_PROVED, prompt)
        self.assertIn("so Scry has not checked any proof", prompt)
        assert isinstance(status, ProofStatus)
        self.assertFalse(status.checked)

    def test_the_helper_is_told_the_status_lean_gave(self) -> None:
        checked = ProofStatus(True, f"{SAYS_PROVED} it. (stand-in)", ("sha256:x",))
        prompt, status = self.prompt_for(checked)
        self.assertIn(checked.text, prompt)
        self.assertIs(status, checked)


if __name__ == "__main__":
    unittest.main()
