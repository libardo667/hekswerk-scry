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


class TestStatementToolbox(unittest.TestCase):
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
            statement_file=statement, solution_module="OAI.Some.Module",
            reports={THEOREM: report},
            paper_files=[build / "main.tex", build / "sections" / "intro.tex"],
        )

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
        lines = self.box.run("read_paper", {"file": "sections/intro.tex", "first_line": 2,
                                            "last_line": 9})
        self.assertEqual(lines.result.splitlines()[0][:6], "   2 |")
        lean_lines = self.box.run("read_lean_lines", {"first_line": 2, "last_line": 3})
        self.assertIn("   3 | line three", lean_lines.result)

    def test_a_lean_claim_must_be_named_and_is_not_run_otherwise(self) -> None:
        unnamed = self.box.run("check_lean_claim", {"lean_code": "example : True := trivial"})
        self.assertIn("theorem scry_check", unnamed.result)
        self.assertEqual(self.box.checks_run, 0)
        self.assertIsNone(unnamed.checked_by)


if __name__ == "__main__":
    unittest.main()
