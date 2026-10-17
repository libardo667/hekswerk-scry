"""End-to-end tests that run the real Lean program.

Run them with `make lean-test` after `make lean-setup`. They are kept apart from the main
test suite because each Lean run takes seconds, and because they need Lean installed.
They fail (never skip) when Lean or the workspace is missing.
"""

import shutil
import unittest
from pathlib import Path

from hekswerk_scry.checker import check_wiring, scan_proof_map
from hekswerk_scry.core.enums import CheckKind, StepStatus, WhatIfKind
from hekswerk_scry.lean.alphaproof import fetch_alphaproof
from hekswerk_scry.lean.checks import LeanSourceMismatchError, check_map_with_lean
from hekswerk_scry.lean.importer import import_theorem
from hekswerk_scry.lean.runner import check_file
from hekswerk_scry.lean.what_if import run_lean_what_if
from hekswerk_scry.lean.workspace import LeanWorkspace, find_workspace
from hekswerk_scry.models import ProofMap, WhatIfChange

THEOREM = "shifted_fraction_ne_one"


def workspace() -> LeanWorkspace:
    return find_workspace(Path(__file__).parent)


def example_map() -> ProofMap:
    ws = workspace()
    return import_theorem(ws, ws.root / "Examples" / "ShiftedFraction.lean", THEOREM)


class TestExampleWithLean(unittest.TestCase):
    def test_import_matches_the_recorded_trace(self) -> None:
        from tests.test_lean_importer import lean_map

        imported = example_map()
        recorded = lean_map()
        self.assertEqual(
            {sid: s.contract for sid, s in imported.steps.items()},
            {sid: s.contract for sid, s in recorded.steps.items()},
        )
        self.assertTrue(check_wiring(imported).passed)

    def test_lean_checks_the_example(self) -> None:
        report = check_map_with_lean(workspace(), example_map())
        self.assertTrue(report.passed, report.check.problems)
        self.assertIs(report.check.receipt.checked_by, CheckKind.LEAN)
        self.assertEqual({v.status for v in report.verdicts.values()}, {StepStatus.LEAN_CHECKED})

    def test_a_broken_copy_is_rejected_at_the_right_step(self) -> None:
        ws = workspace()
        text = (ws.root / "Examples" / "ShiftedFraction.lean").read_text(encoding="utf-8")
        broken = text.replace(":= pow_pos (by linarith) 3", ":= pow_pos (by linarith) 2")
        check = check_file(ws, ws.root / "Examples" / "ShiftedFraction.lean", THEOREM,
                           source_text=broken)
        self.assertFalse(check.passed)
        self.assertEqual(check.errors()[0].line, 12)

    def test_what_if_an_unused_lemma_does_nothing(self) -> None:
        report = run_lean_what_if(
            workspace(), example_map(), WhatIfChange(WhatIfKind.REMOVE_STEP, "s10")
        )
        self.assertTrue(report.goal_reached_after)
        self.assertTrue(report.headline.startswith("Not needed"))
        self.assertIs(report.checked_by, CheckKind.LEAN)

    def test_what_if_a_needed_lemma_does_nothing(self) -> None:
        report = run_lean_what_if(
            workspace(), example_map(), WhatIfChange(WhatIfKind.REMOVE_STEP, "s3")
        )
        self.assertFalse(report.goal_reached_after)
        self.assertEqual([b.step_id for b in report.broken_steps], ["s8"])
        self.assertIn("unknown identifier 'cube_split'", report.broken_steps[0].reasons[0])

    def test_a_map_is_never_checked_against_a_changed_file(self) -> None:
        ws = workspace()
        runs = ws.root / ".scry-runs" / "tests"
        runs.mkdir(parents=True, exist_ok=True)
        copy = runs / "Copy.lean"
        shutil.copy(ws.root / "Examples" / "ShiftedFraction.lean", copy)
        proof_map = import_theorem(ws, copy, THEOREM)
        copy.write_text(copy.read_text(encoding="utf-8") + "\n-- edited\n", encoding="utf-8")
        with self.assertRaises(LeanSourceMismatchError):
            check_map_with_lean(ws, proof_map)


class TestStatementsWithLean(unittest.TestCase):
    def test_an_imo_statement_is_read_without_generated_helpers(self) -> None:
        from hekswerk_scry.lean.statement import read_statement

        ws = workspace()
        p2 = next(path for path, thm in fetch_alphaproof(ws).items() if thm == "imo_2024_p2")
        report = read_statement(ws, p2, "imo_2024_p2")
        self.assertEqual(report.binders, ())
        self.assertTrue(report.conclusion.endswith("= {(1, 1)}"), report.conclusion)
        # `{(a, b) | ...}` makes Lean generate a pattern-matching helper; nobody wrote it,
        # so it isn't listed as a definition to read.
        self.assertEqual(report.definitions, ())
        self.assertFalse(report.proof_left_open)


class TestAlphaProofWithLean(unittest.TestCase):
    def test_all_three_proofs_import_line_up_and_are_lean_checked(self) -> None:
        ws = workspace()
        for path, theorem in fetch_alphaproof(ws).items():
            with self.subTest(theorem=theorem):
                proof_map = import_theorem(ws, path, theorem)
                self.assertGreater(len(proof_map.steps), 50)
                self.assertTrue(check_wiring(proof_map).passed)
                scan_proof_map(proof_map)
                report = check_map_with_lean(ws, proof_map)
                self.assertTrue(report.passed, report.check.problems)


if __name__ == "__main__":
    unittest.main()
