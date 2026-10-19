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

    def test_rcases_and_obtain_keep_what_their_scrutinee_uses(self) -> None:
        ws = workspace()
        runs = ws.root / ".scry-runs" / "tests"
        runs.mkdir(parents=True, exist_ok=True)
        probe = runs / "RcasesObtain.lean"
        probe.write_text(
            "theorem rcases_probe (P Q R : Prop) (hp : Nat → P → P) (hpq : P → Q ∨ R)\n"
            "    (h0 : P) (hq : Q → False) (hr : R → False) : False := by\n"
            "  let k : Nat := 1\n"
            "  have h1 : P := hp k h0\n"
            "  rcases hpq (by exact h1) with h | h\n"
            "  · exact hq h\n"
            "  · exact hr h\n\n"
            "theorem obtain_probe (P Q : Prop) (hpq : P ∧ Q) (h : P → Q → False) : False := by\n"
            "  obtain ⟨hp, hq⟩ := hpq\n"
            "  exact h hp hq\n",
            encoding="utf-8",
        )
        rcases_map = import_theorem(ws, probe, "rcases_probe")
        self.assertEqual(scan_proof_map(rcases_map).unused_steps, ())
        self.assertIn("hpq : P → Q ∨ R", rcases_map.steps["s3"].contract.assumes)
        self.assertIn("s4", rcases_map.steps["s3"].depends_on)
        self.assertEqual(rcases_map.steps["s4"].depends_on, ("s2-why1",))

        obtain_map = import_theorem(ws, probe, "obtain_probe")
        self.assertEqual(scan_proof_map(obtain_map).unused_steps, ())
        self.assertIn("hpq : P ∧ Q", obtain_map.steps["s1"].contract.assumes)

    def test_nested_blocks_under_binders_and_inside_show_are_holes(self) -> None:
        # Lean copies a nested block's finished proof into the surrounding term. Under the
        # binders of `have ha (k) (hk)`, the copy's hypotheses are bound variables; `show T by`
        # writes its block through a macro. Either way the block's step must stay attached.
        ws = workspace()
        runs = ws.root / ".scry-runs" / "tests"
        runs.mkdir(parents=True, exist_ok=True)
        probe = runs / "NestedBlocks.lean"
        probe.write_text(
            "theorem under_binders (n : Nat) (hn : n = 1) : n < 5 := by\n"
            "  have ha (k : Nat) (hk : k ≤ 3) : k < 5 := Nat.lt_of_le_of_lt hk (by omega)\n"
            "  exact ha n (by omega)\n\n"
            "theorem inside_show (n : Nat) (h0 : n = 0) : n + 0 = 0 := by\n"
            "  have hz := (show n + 0 = n by simp)\n"
            "  rw [hz, h0]\n",
            encoding="utf-8",
        )
        for theorem, block in [("under_binders", "omega"), ("inside_show", "simp")]:
            with self.subTest(theorem):
                proof_map = import_theorem(ws, probe, theorem)
                self.assertEqual(scan_proof_map(proof_map).unused_steps, ())
                self.assertEqual(proof_map.steps["s2"].views.code, block)
                self.assertIn("s2", proof_map.steps["s1-why1"].depends_on)


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


    def test_a_private_definition_is_part_of_a_statement_s_meaning(self) -> None:
        # Lean names private declarations `_private.<module>.0.<name>`, which looked like a
        # generated helper's name, so they were silently left off the list to read.
        from tests.test_outline import FIXTURES

        from hekswerk_scry.lean.statement import read_statement

        ws = workspace()
        folder = ws.root / ".scry-runs" / "lean-tests"
        folder.mkdir(parents=True, exist_ok=True)
        copy = folder / "Outline.lean"
        shutil.copy(FIXTURES / "lean" / "Outline.lean", copy)
        report = read_statement(ws, copy, "OutlineExample.double_eq", probes=False)
        self.assertEqual([d.name.rsplit(".", 1)[-1] for d in report.definitions], ["double"])


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


class TestOutlineWithLean(unittest.TestCase):
    def test_the_exporter_makes_the_recorded_outline(self) -> None:
        # tests/test_outline.py reads the exporter's recorded output; this keeps the record
        # honest. Run on a copy in the workspace, as a person's file would be.
        from tests.test_outline import FIXTURES, exporter_output

        from hekswerk_scry.lean.outline import make_outline

        ws = workspace()
        folder = ws.root / ".scry-runs" / "lean-tests"
        folder.mkdir(parents=True, exist_ok=True)
        copy = folder / "Outline.lean"
        shutil.copy(FIXTURES / "lean" / "Outline.lean", copy)
        outline = make_outline(ws, copy, "OutlineExample.result")
        recorded = exporter_output()
        self.assertEqual(list(outline.parts), [p["id"] for p in recorded["parts"]])
        for raw in recorded["parts"]:
            part = outline.parts[raw["id"]]
            self.assertEqual(
                (part.kind, part.statement, part.statement_uses, part.body_uses,
                 [(h.name, h.statement) for h in part.unused_hypotheses]),
                (raw["kind"], raw["statement"], tuple(raw["statement_uses"]),
                 tuple(raw["body_uses"]),
                 [(h["name"], h["statement"]) for h in raw["unused_hypotheses"]]))
        self.assertEqual(list(outline.axioms), recorded["axioms"])
