"""The statement-audit toolbox, without Lean or a model (recorded Lean output)."""

import tempfile
import unittest
from pathlib import Path

from hekswerk_scry.ai.statement_tools import StatementToolbox
from hekswerk_scry.core.enums import CheckKind
from hekswerk_scry.lean.statement import report_from_json
from hekswerk_scry.lean.workspace import LeanWorkspace
from tests.test_statement import EVIDENCE, raw

THEOREM = "OAI.TruffetV4Counterexample.finite_execution_not_optimal"


class ToolboxCase(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        build = root / "preprints" / "Some-Paper" / "build"
        (build / "sections").mkdir(parents=True)
        (build / "main.tex").write_text("\\input{sections/intro}\n", encoding="utf-8")
        (build / "sections" / "intro.tex").write_text(
            "Intro.\n\\begin{theorem}The procedure is not optimal.\\end{theorem}\n",
            encoding="utf-8",
        )
        statement = root / "Statement.lean"
        statement.write_text("line one\nline two\nline three\n", encoding="utf-8")
        report = report_from_json(raw("truffet_challenge"), "Statement.lean", EVIDENCE)
        self.box = StatementToolbox(
            workspace=LeanWorkspace(root=root, lake=root / "lake", exporter=root / "exp"),
            statement_file=statement,
            solution_module="OAI.Some.Module",
            reports={THEOREM: report},
            paper_files=[build / "main.tex", build / "sections" / "intro.tex"],
        )


class TestStatementToolbox(ToolboxCase):
    def test_lean_readings_are_lean_evidence(self) -> None:
        statement = self.box.run("read_statement", {"theorem": THEOREM})
        self.assertIs(statement.checked_by, CheckKind.LEAN)
        self.assertIn("Conclusion: crossRowRestriction initial", statement.result)
        definition = self.box.run("read_definition", {"name": "feasible"})
        self.assertIs(definition.checked_by, CheckKind.LEAN)
        self.assertIn("lines 36-37", definition.result)
        missing = self.box.run("read_definition", {"name": "nonsense"})
        self.assertIn("isn't one of the project definitions", missing.result)
        self.assertIsNone(missing.checked_by)

    def test_paper_files_are_named_inside_the_build_folder(self) -> None:
        listing = self.box.run("list_paper_files", {})
        self.assertIn("main.tex (1 lines)", listing.result)
        self.assertIn("sections/intro.tex (2 lines)", listing.result)
        found = self.box.run("search_paper", {"phrase": "NOT OPTIMAL"})
        self.assertIn("sections/intro.tex:2:", found.result)
        self.assertIsNone(found.checked_by)  # reading the paper is a lookup, not a check
        lines = self.box.run(
            "read_paper", {"file": "sections/intro.tex", "first_line": 2, "last_line": 9}
        )
        self.assertEqual(lines.result.splitlines()[0][:6], "   2 |")
        lean_lines = self.box.run("read_lean_lines", {"first_line": 2, "last_line": 3})
        self.assertIn("   3 | line three", lean_lines.result)

    def test_a_lean_claim_must_be_named_and_is_not_run_otherwise(self) -> None:
        unnamed = self.box.run("check_lean_claim", {"lean_code": "example : True := trivial"})
        self.assertIn("theorem scry_check", unnamed.result)
        self.assertEqual(self.box.checks_run, 0)
        self.assertIsNone(unnamed.checked_by)


class TestRecordedVerdicts(ToolboxCase):
    def good(self, **change: object) -> dict[str, object]:
        return {
            "item": "conclusion",
            "paper_says": "p",
            "lean_says": "l",
            "verdict": "Lean concludes less",
            "affects_main_result": True,
            "lean_first_line": 2,
            "lean_last_line": 3,
            "evidence": ["E1"],
            **change,
        }

    def test_a_good_row_is_recorded_as_given(self) -> None:
        self.box.run("read_lean_lines", {"first_line": 1, "last_line": 3})  # E1
        recorded = self.box.run("record_verdict", self.good(evidence=["[E1]", "E1"]))
        self.assertIsNone(recorded.checked_by)  # a row is the helper's reading, not a check
        self.assertEqual(len(self.box.verdicts), 1)
        row = self.box.verdicts[0]
        self.assertEqual(
            (row.verdict, row.lean_lines, row.evidence), ("Lean concludes less", (2, 3), ("E1",))
        )
        missing = self.box.run(
            "record_verdict",
            self.good(
                verdict="not in the formalization", lean_first_line=None, lean_last_line=None
            ),
        )
        self.assertIn("Recorded row 2", missing.result)
        self.assertIsNone(self.box.verdicts[1].lean_lines)

    def test_bad_rows_are_refused_and_not_recorded(self) -> None:
        self.box.run("read_lean_lines", {"first_line": 1, "last_line": 3})  # E1
        self.box.run("record_verdict", self.good())  # E2, a row: not citable evidence
        cases = [
            (self.good(verdict="mostly fine"), "isn't a verdict"),
            (self.good(lean_first_line=3, lean_last_line=4), "aren't in the statement file"),
            (self.good(lean_first_line=0), "aren't in the statement file"),
            (self.good(lean_first_line=3, lean_last_line=2), "aren't in the statement file"),
            (self.good(lean_first_line=None, lean_last_line=None), "only 'not in the"),
            (self.good(lean_last_line=None), "both lean_first_line"),
            (self.good(evidence=["E9"]), "aren't any: E9"),
            (self.good(evidence=["E2"]), "aren't any: E2"),
            (self.good(evidence=[]), "Cite at least one"),
            (self.good(affects_main_result="yes"), "true or false"),
        ]
        for arguments, message in cases:
            with self.subTest(message):
                refused = self.box.run("record_verdict", arguments)
                self.assertIn(message, refused.result)
        self.assertEqual(len(self.box.verdicts), 1)

    def test_rows_must_point_at_specific_lines(self) -> None:
        self.box.statement_file.write_text("x\n" * 100, encoding="utf-8")
        self.box.run("read_lean_lines", {"first_line": 1, "last_line": 3})
        wide = self.box.run("record_verdict", self.good(lean_first_line=1, lean_last_line=26))
        self.assertIn("specific lines", wide.result)
        exact = self.box.run("record_verdict", self.good(lean_first_line=1, lean_last_line=25))
        self.assertIn("Recorded row 1", exact.result)


if __name__ == "__main__":
    unittest.main()
