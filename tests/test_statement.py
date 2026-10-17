"""Reading Lean's statement reports, and the stored results (no Lean needed).

The fixtures are real exporter output (see tests/fixtures/statements/README.md).
"""

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from hekswerk_scry.lean.statement import (
    StatementReport,
    read_statement,
    report_from_json,
    stored_result_path,
)
from hekswerk_scry.lean.workspace import LeanWorkspace
from hekswerk_scry.models.receipts import LeanRunEvidence
from hekswerk_scry.text_reports import render_statement

FIXTURES = Path(__file__).parent / "fixtures" / "statements"
EVIDENCE = LeanRunEvidence(("lake", "env", "scry-export"), 0, False, "0" * 64, 1.0)


def raw(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data


def report(name: str) -> StatementReport:
    return report_from_json(raw(name), "Probes.lean", EVIDENCE)


class TestProbes(unittest.TestCase):
    def test_contradictory_hypotheses_are_a_red_flag(self) -> None:
        vacuous = report("probe_vacuous")
        self.assertEqual([p.kind for p in vacuous.red_flags], ["vacuity"])
        self.assertIn(
            "derived False from the hypotheses (with `omega`)", vacuous.red_flags[0].headline
        )
        self.assertFalse(vacuous.receipt.passed)
        self.assertIn("vacuity", vacuous.receipt.summary)

    def test_unneeded_hypotheses_are_a_red_flag(self) -> None:
        trivial = report("probe_trivial")
        self.assertEqual([p.kind for p in trivial.red_flags], ["triviality"])
        self.assertIn("without the hypotheses", trivial.red_flags[0].headline)

    def test_finding_nothing_is_reported_as_nothing(self) -> None:
        honest = report("probe_honest")
        self.assertEqual(honest.red_flags, ())
        self.assertTrue(honest.receipt.passed)
        self.assertIn("which proves nothing", honest.receipt.summary)
        shown = render_statement(honest)
        self.assertIn("does not show they are consistent", " ".join(shown.split()))
        self.assertIn("h : 1 < x", shown)
        self.assertIn("x : ℝ  (explicit)", shown)


class TestChallengeStatement(unittest.TestCase):
    def test_a_comparator_challenge_is_a_statement_not_a_proof(self) -> None:
        truffet = report_from_json(raw("truffet_challenge"), "Truffet.lean", EVIDENCE)
        self.assertTrue(truffet.proof_left_open)
        self.assertEqual(truffet.binders, ())
        self.assertTrue(all(not p.applicable for p in truffet.probes))
        self.assertEqual(truffet.red_flags, ())
        self.assertEqual(len(truffet.definitions), 37)
        names = {d.name.split(".")[-1] for d in truffet.definitions}
        self.assertTrue({"feasible", "eval", "State", "dominating"} <= names)
        self.assertTrue(truffet.conclusion.startswith("crossRowRestriction initial ∧"))
        shown = render_statement(truffet)
        self.assertIn("it is a statement to check, not a proof", shown)
        self.assertIn("Assuming: nothing (no hypotheses)", shown)
        self.assertIn("37 definition(s) from the project itself", shown)


class TestStoredResults(unittest.TestCase):
    def test_a_stored_result_is_reused_only_for_exactly_the_same_run(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "lean-toolchain").write_text("leanprover/lean4:v4.34.1\n", encoding="utf-8")
            lean_file = root / "Probes.lean"
            lean_file.write_text("theorem probe_honest : True := trivial\n", encoding="utf-8")
            exporter = root / "scry-export"
            exporter.write_bytes(b"exporter build 1")
            ws = LeanWorkspace(root=root, lake=root / "no-lake-here", exporter=exporter)
            # No stored result: Scry must try to run Lean (and here it can't).
            with self.assertRaises(OSError):
                read_statement(ws, lean_file, "probe_honest")
            # Store one, as a real run would.
            stored = stored_result_path(ws, lean_file, "probe_honest", probes=True)
            stored.parent.mkdir(parents=True)
            stored.write_text(
                json.dumps(
                    {
                        "ran_at": "2026-10-17 05:40:00",
                        "report": raw("probe_honest"),
                        "evidence": EVIDENCE.to_dict(),
                    }
                ),
                encoding="utf-8",
            )
            reused = read_statement(ws, lean_file, "probe_honest")
            self.assertEqual(reused.reused_from, "2026-10-17 05:40:00")
            self.assertIn("Reused the stored result", render_statement(reused))
            # A different exporter build, or a changed file, must not reuse it.
            exporter.write_bytes(b"exporter build 2")
            with self.assertRaises(OSError):
                read_statement(ws, lean_file, "probe_honest")
            exporter.write_bytes(b"exporter build 1")
            lean_file.write_text("theorem probe_honest : True := by trivial\n", encoding="utf-8")
            with self.assertRaises(OSError):
                read_statement(ws, lean_file, "probe_honest")


if __name__ == "__main__":
    unittest.main()
