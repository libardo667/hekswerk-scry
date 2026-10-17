"""Scry on OpenAI's mathematics repository, with real Lean v4.34.1.

Needs `scry fetch-openai-math` and `make openai-setup`. Slow: each Lean run loads Mathlib,
which takes a minute or two. Results of statement runs are stored, so reruns are faster.
"""

import shutil
import unittest
from pathlib import Path

from hekswerk_scry.checker import check_wiring
from hekswerk_scry.lean import openai_math
from hekswerk_scry.lean.checks import check_map_with_lean, workspace_of
from hekswerk_scry.lean.importer import import_theorem
from hekswerk_scry.lean.runner import check_file
from hekswerk_scry.lean.statement import StatementError, read_statement
from hekswerk_scry.lean.workspace import LeanWorkspace, find_workspace, workspace_for_file

REPOSITORY = Path(__file__).parents[1]


def scratch(workspace: LeanWorkspace, name: str, source: Path) -> Path:
    folder = workspace.root / ".scry-runs" / "openai-tests"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    shutil.copy(source, target)
    return target


class TestTwoLeanVersions(unittest.TestCase):
    def test_both_exporters_make_the_same_map_of_the_same_proof(self) -> None:
        # The bundled example, under Lean v4.10.0-rc2 (AlphaProof's Mathlib) and under
        # Lean v4.34.1 (OpenAI's Mathlib). The exporter was ported between them.
        old_ws = find_workspace(REPOSITORY)
        old = import_theorem(old_ws, old_ws.root / "Examples" / "ShiftedFraction.lean",
                             "shifted_fraction_ne_one")
        new_ws = workspace_for_file(openai_math.lean_project() / "lean-toolchain")
        copy = scratch(new_ws, "ShiftedFraction.lean",
                       REPOSITORY / "lean" / "Examples" / "ShiftedFraction.lean")
        new = import_theorem(new_ws, copy, "shifted_fraction_ne_one")
        self.assertNotEqual(old_ws.toolchain, new_ws.toolchain)
        self.assertEqual({k: (s.contract, s.depends_on) for k, s in old.steps.items()},
                         {k: (s.contract, s.depends_on) for k, s in new.steps.items()})


class TestStatementProbesWithLean(unittest.TestCase):
    def test_known_red_flags_are_found_and_nothing_else(self) -> None:
        ws = workspace_for_file(openai_math.lean_project() / "lean-toolchain")
        probes = scratch(ws, "Probes.lean",
                         REPOSITORY / "tests" / "fixtures" / "lean" / "v4_34" / "Probes.lean")
        found = {
            theorem: [p.kind for p in read_statement(ws, probes, theorem).red_flags]
            for theorem in ("probe_vacuous", "probe_trivial", "probe_honest")
        }
        self.assertEqual(found, {"probe_vacuous": ["vacuity"], "probe_trivial": ["triviality"],
                                 "probe_honest": []})


class TestKeptRunningLeanOnV434(unittest.TestCase):
    def test_files_with_different_imports_in_turn(self) -> None:
        # Loading a second set of imports into one Lean v4.34.1 process broke its
        # environment (even `Fin` was unknown). Each set now gets its own process.
        ws = workspace_for_file(openai_math.lean_project() / "lean-toolchain")
        folder = ws.root / ".scry-runs" / "openai-tests"
        folder.mkdir(parents=True, exist_ok=True)
        files = [
            ("SmallImports", "import Mathlib.Tactic\n\n"
             "theorem p (x : ℕ) (h : 2 < x) : 0 < x := by omega\n", True),
            ("AllOfMathlib", "import Mathlib\n\ntheorem p : Fin 3 = Fin 3 := rfl\n", True),
            ("SmallAgain", "import Mathlib.Tactic\n\ntheorem p (x : ℕ) : 0 < x := by omega\n",
             False),
            ("AllAgain", "import Mathlib\n\ntheorem p : (2 : WithBot ℝ) = 2 := rfl\n", True),
        ]
        for name, text, accepted in files:
            path = folder / f"{name}.lean"
            path.write_text(text, encoding="utf-8")
            fresh = check_file(ws, path, "p", fresh=True)
            kept = check_file(ws, path, "p")
            with self.subTest(name):
                self.assertEqual(fresh.passed, accepted, fresh.problems)
                self.assertEqual((kept.passed, kept.problems, kept.messages),
                                 (fresh.passed, fresh.problems, fresh.messages))

    def test_the_same_files_as_on_lean_v4_10_get_the_same_judgment_both_ways(self) -> None:
        from lean_tests.test_lean_worker import FILES, outcome

        ws = workspace_for_file(openai_math.lean_project() / "lean-toolchain")
        folder = ws.root / ".scry-runs" / "openai-tests" / "both-ways"
        folder.mkdir(parents=True, exist_ok=True)
        for name, theorem, text, accepted in FILES:
            path = folder / f"{name}.lean"
            path.write_text(text, encoding="utf-8")
            fresh = check_file(ws, path, theorem, fresh=True)
            kept = check_file(ws, path, theorem)
            with self.subTest(name):
                self.assertEqual(fresh.passed, accepted, fresh.problems)
                self.assertEqual(outcome(kept), outcome(fresh))

    def test_a_statement_is_not_read_from_a_file_lean_rejects(self) -> None:
        ws = workspace_for_file(openai_math.lean_project() / "lean-toolchain")
        path = ws.root / ".scry-runs" / "openai-tests" / "Rejected.lean"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("import Mathlib.Tactic\n\ntheorem p : Unknown = 1 := sorry\n",
                        encoding="utf-8")
        with self.assertRaisesRegex(StatementError, r"Lean reported \d+ error\(s\) in the "
                                    r"file, so Scry won't read it\. The first: line 3: Unknown "
                                    "identifier `Unknown`"):
            read_statement(ws, path, "p", probes=False)


class TestTruffetCounterexample(unittest.TestCase):
    def test_statement_proof_map_and_lean_check(self) -> None:
        item = openai_math.challenge("TruffetCounterexample")
        ws = workspace_for_file(item.statement_file)
        statement = read_statement(ws, item.statement_file, item.theorem_names[0])
        self.assertTrue(statement.proof_left_open)
        self.assertGreaterEqual(len(statement.definitions), 30)
        proof_map = import_theorem(ws, item.solution_file, item.theorem_names[0])
        self.assertTrue(check_wiring(proof_map).passed)
        self.assertIsNotNone(proof_map.lean_source)
        report = check_map_with_lean(workspace_of(proof_map), proof_map)
        self.assertTrue(report.passed, report.check.problems)


if __name__ == "__main__":
    unittest.main()
