"""Reading Lean's statement reports, and the stored results (no Lean needed).

The fixtures are real exporter output (see tests/fixtures/statements/README.md).
"""

import json
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

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


class TestProbeAxioms(unittest.TestCase):
    def test_a_proof_through_sorry_is_not_a_red_flag(self) -> None:
        # Real exporter output: `simp_all` "derives False" only through a lemma left as
        # `sorry`. The control, on the same theorem, is found on standard axioms.
        shaky = report("untrusted_probe")
        self.assertEqual([p.kind for p in shaky.red_flags], ["triviality"])
        vacuity = next(p for p in shaky.probes if p.kind == "vacuity")
        self.assertFalse(vacuity.found)
        self.assertEqual([(u.tactic, u.axioms) for u in vacuity.untrusted],
                         [("simp_all", ("propext", "sorryAx"))])
        self.assertIn("relying on sorryAx", vacuity.headline)
        self.assertIn("shows nothing about the statement", vacuity.headline)
        self.assertNotIn("Red flag", vacuity.headline)

    def test_a_report_counting_a_proof_through_sorry_as_found_is_refused(self) -> None:
        for extra in (["sorryAx"], ["propext", "my_project_axiom"]):
            data = raw("probe_honest")
            data["probes"]["vacuity"] = {"found": True, "tactic": "simp_all", "axioms": extra,
                                         "untrusted": []}
            with self.subTest(axioms=extra), self.assertRaisesRegex(
                    ValueError, "beyond Lean's standard axioms"):
                report_from_json(data, "Probes.lean", EVIDENCE)


class TestDefinitionCount(unittest.TestCase):
    def test_a_cut_off_list_of_definitions_says_so(self) -> None:
        truffet = report_from_json(raw("truffet_challenge"), "Truffet.lean", EVIDENCE)
        self.assertTrue(truffet.definitions_complete)
        self.assertNotIn("Only the first", render_statement(truffet))
        data = raw("truffet_challenge")
        data["definitions_total"] = 50
        cut = report_from_json(data, "Truffet.lean", EVIDENCE)
        self.assertFalse(cut.definitions_complete)
        self.assertIn("Only the first 37 of 50 are listed", " ".join(render_statement(cut).split()))


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


def project(root: Path) -> LeanWorkspace:
    (root / "lean-toolchain").write_text("leanprover/lean4:v4.34.1\n", encoding="utf-8")
    (root / "lake-manifest.json").write_text(json.dumps({"packages": [
        {"name": "mathlib", "type": "git", "rev": "aaaa"},
        {"name": "local", "type": "path", "dir": "vendor/local"}]}), encoding="utf-8")
    git = root / ".lake" / "packages" / "mathlib" / ".git"
    git.mkdir(parents=True)
    (git / "HEAD").write_text("aaaa\n", encoding="utf-8")
    (root / "vendor" / "local").mkdir(parents=True)
    (root / "vendor" / "local" / "Local.lean").write_text("def l := 1\n", encoding="utf-8")
    (root / "Claim.lean").write_text("import Meaning\nimport Mathlib\ntheorem t : Flag := sorry\n",
                                     encoding="utf-8")
    (root / "Meaning.lean").write_text("import Deeper\ndef Flag : Prop := Deep\n",
                                       encoding="utf-8")
    (root / "Deeper.lean").write_text("def Deep : Prop := True\n", encoding="utf-8")
    (root / "Unrelated.lean").write_text("def u := 1\n", encoding="utf-8")
    exporter = root / "scry-export"
    exporter.write_bytes(b"exporter build 1")
    return LeanWorkspace(root=root, lake=root / "no-lake-here", exporter=exporter)


class TestWhatAStatementReadingDependsOn(unittest.TestCase):
    """A stored reading stands only while every input of Lean's answer is unchanged."""

    def test_every_input_changes_the_key_and_nothing_else_does(self) -> None:
        def edit(text: str) -> Callable[[Path], object]:
            return lambda path: path.write_text(path.read_text(encoding="utf-8") + text,
                                                encoding="utf-8")

        changes: list[tuple[str, str, Callable[[Path], object], bool]] = [
            ("the theorem's file", "Claim.lean", edit("-- edited\n"), True),
            ("an imported definition", "Meaning.lean", edit("def more := 2\n"), True),
            ("a definition imported through another file", "Deeper.lean",
             edit("def more := 2\n"), True),
            ("an imported file going missing", "Deeper.lean", Path.unlink, True),
            ("the package manifest", "lake-manifest.json", edit(" "), True),
            ("the lakefile appearing", "lakefile.lean", lambda p: p.write_text("-- new\n"), True),
            ("a package checked out at another commit", ".lake/packages/mathlib/.git/HEAD",
             lambda p: p.write_text("bbbb\n"), True),
            ("a local package's Lean file", "vendor/local/Local.lean", edit("def m := 2\n"),
             True),
            ("a project file nothing imports", "Unrelated.lean", edit("def v := 2\n"), False),
        ]
        for what, name, change, matters in changes:
            with self.subTest(what), tempfile.TemporaryDirectory() as folder:
                ws = project(Path(folder))
                claim = ws.root / "Claim.lean"
                before = stored_result_path(ws, claim, "t", probes=True)
                change(ws.root / name)
                after = stored_result_path(ws, claim, "t", probes=True)
                self.assertEqual(before != after, matters)

    def test_an_edited_import_means_lean_reads_the_statement_again(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            ws = project(Path(folder))
            claim = ws.root / "Claim.lean"
            data = raw("probe_honest")
            with patch.object(LeanWorkspace, "build_imports") as build, patch(
                    "hekswerk_scry.lean.statement.run_exporter",
                    return_value=(data, EVIDENCE)) as exporter:
                read_statement(ws, claim, "probe_honest")
                again = read_statement(ws, claim, "probe_honest")
                self.assertIsNotNone(again.reused_from)
                (ws.root / "Deeper.lean").write_text("def Deep : Prop := False\n",
                                                     encoding="utf-8")
                fresh = read_statement(ws, claim, "probe_honest")
            self.assertIsNone(fresh.reused_from)
            self.assertEqual(exporter.call_count, 2)
            self.assertEqual(build.call_count, 2)


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
