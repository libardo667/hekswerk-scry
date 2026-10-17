"""The AI helper's Lean tools, run against real Lean with no AI involved."""

import unittest
from pathlib import Path

from hekswerk_scry.ai.tools import Toolbox
from hekswerk_scry.core.enums import CheckKind
from hekswerk_scry.lean.importer import import_theorem
from hekswerk_scry.lean.workspace import find_workspace


class TestToolsWithLean(unittest.TestCase):
    def setUp(self) -> None:
        ws = find_workspace(Path(__file__).parent)
        proof_map = import_theorem(ws, ws.root / "Examples" / "ShiftedFraction.lean",
                                   "shifted_fraction_ne_one")
        self.toolbox = Toolbox(proof_map=proof_map, workspace=ws)

    def test_what_if_and_cards_are_lean_evidence(self) -> None:
        needed = self.toolbox.run("test_step_doing_nothing", {"step_id": "s3"})
        self.assertIs(needed.checked_by, CheckKind.LEAN)
        self.assertIn("Lean rejects the changed proof", needed.result)
        card = self.toolbox.run("try_new_proof", {"step_id": "s7-why1", "tactics": "linarith",
                                                  "why": "direct"})
        self.assertIs(card.checked_by, CheckKind.LEAN)
        self.assertIsNotNone(card.receipt_id)
        self.assertIn("Card C1: Ready to swap", card.result)
        bad = self.toolbox.run("try_new_proof", {"step_id": "s7-why1", "tactics": "sorry",
                                                 "why": "cheat"})
        self.assertIn("Card C2: Rejected", bad.result)
        self.assertEqual([e.evidence_id for e in self.toolbox.evidence], ["E1", "E2", "E3"])

    def test_code_and_regions(self) -> None:
        code = self.toolbox.run("read_lean_code", {"first_line": 15, "last_line": 17})
        self.assertIn("  15 |   have shift_pos", code.result)
        self.assertIsNone(code.checked_by)
        region = self.toolbox.run("show_fact_proof", {"step_id": "s7-why1"})
        self.assertIn('"replaces_lines": [\n  15,\n  17\n ]', region.result)


if __name__ == "__main__":
    unittest.main()
