"""The AI helper with the real model. Costs money (about $0.20 a run); `make ai-test`.

These tests check what the helper *does*, not what it says: before answering a hunch it
must run a Lean check on the step in question, and its answer must cite that check.
"""

import unittest
from pathlib import Path

from hekswerk_scry.ai.openrouter import OpenRouterClient
from hekswerk_scry.ai.session import Session
from hekswerk_scry.ai.tools import Toolbox
from hekswerk_scry.core.enums import CheckKind
from hekswerk_scry.core.settings import load_ai_settings
from hekswerk_scry.lean.importer import import_theorem
from hekswerk_scry.lean.workspace import find_workspace


class TestLiveHelper(unittest.TestCase):
    def test_a_wrong_hunch_is_checked_with_lean_before_it_is_answered(self) -> None:
        ws = find_workspace(Path(__file__).parent)
        proof_map = import_theorem(ws, ws.root / "Examples" / "ShiftedFraction.lean",
                                   "shifted_fraction_ne_one")
        session = Session(OpenRouterClient(load_ai_settings(Path(__file__).parent)),
                          Toolbox(proof_map=proof_map, workspace=ws))
        # Lean says s3 (cube_split) IS needed: removing it breaks the `rw` in s8.
        turn = session.ask("I'm sure step s3 (cube_split) is pointless and can just be "
                           "deleted. Agreed?")
        lean_checks_of_s3 = [
            e for e in turn.evidence
            if e.checked_by is CheckKind.LEAN and e.arguments.get("step_id") == "s3"
        ]
        self.assertTrue(lean_checks_of_s3, [e.label for e in turn.evidence])
        cited_ids = {e.evidence_id for e in turn.cited}
        self.assertTrue(cited_ids & {e.evidence_id for e in lean_checks_of_s3}, turn.answer)
        self.assertEqual(turn.unknown_citations, [])
        print(f"\n(live test cost ${session.total_cost_usd:.4f})")


if __name__ == "__main__":
    unittest.main()
