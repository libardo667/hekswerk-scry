"""Simplification cards judged by the real Lean program. Run with `make lean-test`."""

import shutil
import unittest
from pathlib import Path

from hekswerk_scry.checker import check_wiring
from hekswerk_scry.core.enums import CardStatus, CheckKind
from hekswerk_scry.lean.alphaproof import fetch_alphaproof
from hekswerk_scry.lean.cards import (
    LeanCardRejectedError,
    apply_lean_card,
    check_lean_card,
    draft_lean_card,
)
from hekswerk_scry.lean.importer import import_theorem
from hekswerk_scry.lean.workspace import LeanWorkspace, find_workspace
from hekswerk_scry.models import ProofMap

THEOREM = "shifted_fraction_ne_one"


def workspace() -> LeanWorkspace:
    return find_workspace(Path(__file__).parent)


class TestCardsOnTheExample(unittest.TestCase):
    """Each test works on its own copy of the example, so the original is never touched."""

    def setUp(self) -> None:
        self.ws = workspace()
        self.folder = self.ws.root / ".scry-runs" / "card-tests" / self.id().split(".")[-1]
        shutil.rmtree(self.folder, ignore_errors=True)
        self.folder.mkdir(parents=True)
        self.lean_file = self.folder / "Example.lean"
        shutil.copy(self.ws.root / "Examples" / "ShiftedFraction.lean", self.lean_file)
        self.map: ProofMap = import_theorem(self.ws, self.lean_file, THEOREM)

    def card(self, fact: str, replacement: str) -> CardStatus:
        card = draft_lean_card(self.ws, self.map, fact, card_id="c", title="t", why="w",
                               replacement=replacement)
        self.last = check_lean_card(self.ws, self.map, card)
        return self.last.status

    def test_a_direct_proof_of_the_detour_is_accepted_and_applied(self) -> None:
        card = draft_lean_card(self.ws, self.map, "s7-why1", card_id="direct", title="t",
                               why="w", replacement="linarith")
        check = check_lean_card(self.ws, self.map, card)
        self.assertIs(check.status, CardStatus.READY_TO_SWAP, check.problems)
        assert check.receipt is not None and check.receipt.lean_run is not None
        self.assertIs(check.receipt.checked_by, CheckKind.LEAN)

        before = self.lean_file.read_text(encoding="utf-8")
        out = self.folder / "Simpler.lean"
        new_map, receipt = apply_lean_card(self.ws, self.map, card, out)
        self.assertEqual(self.lean_file.read_text(encoding="utf-8"), before)  # untouched
        self.assertTrue(out.is_file())
        self.assertEqual(new_map.goal, self.map.goal)
        self.assertTrue(check_wiring(new_map).passed)
        # Trying a card uses the kept-running Lean; the check that allows the swap is a new
        # Lean process, every time.
        self.assertIn("--serve", check.receipt.lean_run.command)
        assert receipt.lean_run is not None
        self.assertNotIn("--serve", receipt.lean_run.command)
        # shift_pos (have, why, linarith) + sq_nonneg_x (have, why) + lt_shift (have, why,
        # linarith) + below_one (have, why) + the final exact = 11 steps; it was 22.
        self.assertEqual(len(new_map.steps), 11)
        self.assertTrue(all(sid.startswith("v1.") for sid in new_map.archived_steps))
        record = new_map.history[0]
        self.assertEqual(record.receipt_id, receipt.receipt_id)
        assert record.lean_before is not None and record.lean_after is not None
        self.assertEqual(record.lean_before.file_sha256, self.map.lean_source.file_sha256)  # type: ignore[union-attr]
        self.assertEqual(record.lean_after.file_sha256, new_map.lean_source.file_sha256)  # type: ignore[union-attr]
        self.assertEqual(record.added_step_ids, ("s2",))  # the new `linarith` in shift_pos

    def test_sorry_is_rejected(self) -> None:
        self.assertIs(self.card("s7-why1", "sorry"), CardStatus.REJECTED)
        self.assertIn("sorry", " ".join(self.last.problems))

    def test_a_wrong_tactic_is_rejected_at_its_line(self) -> None:
        self.assertIs(self.card("s7-why1", "skip\nexact hx"), CardStatus.REJECTED)
        self.assertTrue(self.last.problems[0].startswith("Your replacement, line 2:"),
                        self.last.problems)

    def test_trying_to_declare_an_axiom_is_rejected(self) -> None:
        status = self.card("s7-why1", "exact cheat\naxiom cheat : x + 7 > 0")
        self.assertIs(status, CardStatus.REJECTED)

    def test_the_new_proof_cannot_use_what_it_replaces(self) -> None:
        # cube_pos is removed along with the detour, so the new proof can't rely on it.
        self.assertIs(self.card("s7-why1", "exact pos_of_mul_pos_left cube_pos le_rfl"),
                      CardStatus.REJECTED)

    def test_a_card_goes_stale_when_the_file_changes(self) -> None:
        card = draft_lean_card(self.ws, self.map, "s7-why1", card_id="c", title="t", why="w",
                               replacement="linarith")
        self.lean_file.write_text(
            self.lean_file.read_text(encoding="utf-8") + "\n-- edited\n", encoding="utf-8"
        )
        changed = import_theorem(self.ws, self.lean_file, THEOREM)
        self.assertIs(check_lean_card(self.ws, changed, card).status, CardStatus.STALE)

    def test_apply_refuses_to_overwrite_and_rechecks(self) -> None:
        card = draft_lean_card(self.ws, self.map, "s7-why1", card_id="c", title="t", why="w",
                               replacement="sorry")
        with self.assertRaises(LeanCardRejectedError):
            apply_lean_card(self.ws, self.map, card, self.folder / "New.lean")
        self.assertFalse((self.folder / "New.lean").exists())
        with self.assertRaisesRegex(ValueError, "won't overwrite"):
            apply_lean_card(self.ws, self.map, card, self.lean_file)


class TestCardOnAlphaProof(unittest.TestCase):
    def test_the_p2_detour_deepmind_flagged_can_be_removed(self) -> None:
        # DeepMind's comment in P2: "The agent wastes the next 16 lines proving then
        # discarding a lemma." Re-prove that goal (step s7, `False`) with only the direct
        # proof that follows `exfalso`, copied verbatim.
        ws = workspace()
        p2 = next(path for path, thm in fetch_alphaproof(ws).items() if thm == "imo_2024_p2")
        proof_map = import_theorem(ws, p2, "imo_2024_p2")
        lines = p2.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[38].strip(), "exfalso")  # line 39 of the file
        direct = "\n".join(lines[39:85])  # lines 40-85: the direct proof of False
        card = draft_lean_card(ws, proof_map, "s7", card_id="p2-detour", title="t", why="w",
                               replacement=direct)
        check = check_lean_card(ws, proof_map, card)
        self.assertIs(check.status, CardStatus.READY_TO_SWAP, check.problems)
        self.assertEqual(check.lines_replaced - check.lines_added, 16)


if __name__ == "__main__":
    unittest.main()
