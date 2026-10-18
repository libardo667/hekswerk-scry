"""The statement-audit benchmark's plumbing: plants, copies, scoring, and blindness.

No Lean and no model: the parts that decide what a score means are tested on their own.
"""

import json
import tempfile
import unittest
from pathlib import Path

from hekswerk_scry.ai import benchmark
from hekswerk_scry.ai.audit import audit_prompt
from hekswerk_scry.ai.benchmark import (
    CAUGHT,
    COPY_CLAIM_NOTE,
    COPY_PROOF_NOTE,
    COPY_STATUS,
    DANGEROUS_MISS,
    MISSED,
    BenchmarkError,
    Plant,
    control_flagged,
    copy_folder,
    load_plants,
    plant_into,
    score_plant,
    without_theorems,
)
from hekswerk_scry.ai.statement_tools import MATCHES, StatementToolbox, VerdictRow
from hekswerk_scry.lean import openai_math
from hekswerk_scry.lean.statement import report_from_json
from hekswerk_scry.lean.workspace import LeanWorkspace
from tests.test_statement import EVIDENCE, raw

STATEMENT = """import Mathlib

namespace OAI
namespace Thing

def Nice (n : ℕ) : Prop :=
  2 < n

/-- The main result,
over two lines. -/
theorem main (n : ℕ) (h : Nice n) :
    0 < n := by
  sorry

theorem other : True := by sorry

end Thing
end OAI
"""


def row(verdict: str, lines: tuple[int, int] | None) -> VerdictRow:
    return VerdictRow("item", "paper", "lean", verdict, True, lines, ("E1",))


class TestPlants(unittest.TestCase):
    def plant(self, old: str, new: str) -> Plant:
        return Plant("Thing", "p", "constant", "what", old, new)

    def test_a_plant_lands_on_the_lines_it_reports(self) -> None:
        for old, new in [
            ("  2 < n", "  3 < n"),
            ("  2 < n", "  2 < n ∧\n    n < 100"),
            ("    0 < n := by", "    0 ≤ n := by"),
        ]:
            text, planted, original = plant_into(STATEMENT, self.plant(old, new))
            lines = text.split("\n")
            self.assertEqual("\n".join(lines[planted[0] - 1 : planted[1]]), new)
            self.assertEqual("\n".join(STATEMENT.split("\n")[original[0] - 1 : original[1]]), old)
            # Nothing else changed.
            self.assertEqual(text.replace(new, old), STATEMENT)

    def test_a_plant_must_match_exactly_once(self) -> None:
        with self.assertRaisesRegex(BenchmarkError, "occurs 0 times"):
            plant_into(STATEMENT, self.plant("  5 < n", "  6 < n"))
        with self.assertRaisesRegex(BenchmarkError, "occurs 2 times"):
            plant_into(STATEMENT, self.plant("namespace", "section"))

    def test_the_plants_file_is_checked(self) -> None:
        plants = load_plants()
        self.assertTrue(plants)
        self.assertTrue(all(len(p) >= 1 for p in plants.values()))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "plants.json"
            base: dict[str, object] = {
                "format": benchmark.PLANTS_FORMAT,
                "version": 1,
                "challenges": {
                    "T": [{"id": "a", "kind": "k", "what": "w", "old": "x", "new": "y"}]
                },
            }
            cases: list[tuple[dict[str, object], str]] = [
                ({"extra": 1}, "fields Scry doesn't know"),
                ({"format": "other"}, "is not a"),
                (
                    {"challenges": {"T": [{"id": "a", "kind": "k", "what": "w", "old": "x"}]}},
                    "exactly the fields",
                ),
                (
                    {
                        "challenges": {
                            "T": [
                                {"id": "control", "kind": "k", "what": "w", "old": "x", "new": "y"}
                            ]
                        }
                    },
                    "used twice",
                ),
                (
                    {
                        "challenges": {
                            "T": [{"id": "a", "kind": "k", "what": "w", "old": "x", "new": "x"}]
                        }
                    },
                    "changes nothing",
                ),
            ]
            for change, message in cases:
                path.write_text(json.dumps({**base, **change}), encoding="utf-8")
                with self.subTest(message), self.assertRaisesRegex(BenchmarkError, message):
                    load_plants(path)


class TestTheoremsTakenOut(unittest.TestCase):
    def test_the_theorem_and_its_comment_go_and_nothing_else(self) -> None:
        stripped = without_theorems(STATEMENT, ("OAI.Thing.main",))
        self.assertEqual(
            stripped,
            STATEMENT.replace(
                "/-- The main result,\nover two lines. -/\ntheorem main (n : ℕ) (h : Nice n) :\n"
                "    0 < n := by\n  sorry\n",
                "",
            ),
        )
        both = without_theorems(STATEMENT, ("OAI.Thing.main", "OAI.Thing.other"))
        self.assertNotIn("sorry", both)
        self.assertIn("def Nice", both)
        self.assertIn("end OAI", both)

    def test_it_refuses_what_it_cannot_find(self) -> None:
        with self.assertRaisesRegex(BenchmarkError, "found 0"):
            without_theorems(STATEMENT, ("OAI.Thing.missing",))
        with self.assertRaisesRegex(BenchmarkError, "doesn't end in `sorry`"):
            without_theorems("theorem main : True := trivial\n", ("main",))
        twice = STATEMENT + "\ntheorem main : True := by sorry\n"
        with self.assertRaisesRegex(BenchmarkError, "found 2"):
            without_theorems(twice, ("OAI.Thing.main",))
        # `main` must not match `mainly`.
        self.assertIn(
            "theorem mainly",
            without_theorems(
                STATEMENT.replace("theorem other", "theorem mainly"), ("OAI.Thing.main",)
            ),
        )


class TestScoring(unittest.TestCase):
    def test_the_three_outcomes(self) -> None:
        planted = (10, 11)
        self.assertEqual(score_plant([row("differs", (11, 12))], planted), CAUGHT)
        self.assertEqual(score_plant([row(MATCHES, (9, 10))], planted), DANGEROUS_MISS)
        self.assertEqual(
            score_plant([row("differs", (12, 20)), row(MATCHES, (1, 9))], planted), MISSED
        )
        self.assertEqual(score_plant([row("not in the formalization", None)], planted), MISSED)
        self.assertEqual(score_plant([], planted), MISSED)
        # A flag anywhere over the lines wins over a "matches" over them.
        self.assertEqual(
            score_plant([row(MATCHES, (10, 10)), row("unclear", (8, 10))], planted), CAUGHT
        )

    def test_scores_depend_only_on_rows_over_the_planted_lines(self) -> None:
        # Invariant: adding rows that don't touch the planted lines never changes a score.
        planted = (20, 22)
        far = [
            row(v, lines) for v in (MATCHES, "differs") for lines in ((1, 19), (23, 40), (5, 5))
        ] + [row("differs", None)]
        for rows in ([row("differs", (22, 25))], [row(MATCHES, (18, 20))], []):
            with self.subTest(rows=rows):
                self.assertEqual(score_plant(rows + far, planted), score_plant(rows, planted))

    def test_control_flags_are_noticed(self) -> None:
        self.assertTrue(control_flagged([row("differs", (5, 7))], (7, 7)))
        self.assertFalse(control_flagged([row(MATCHES, (5, 7))], (7, 7)))
        self.assertFalse(control_flagged([row("differs", (8, 9))], (7, 7)))


class TestBudget(unittest.TestCase):
    def test_an_audit_starts_only_if_the_dearest_one_so_far_still_fits(self) -> None:
        self.assertTrue(benchmark.can_afford([], 1.0))
        self.assertTrue(benchmark.can_afford([0.5, 1.0], 3.0))
        self.assertFalse(benchmark.can_afford([0.5, 1.0], 2.49))
        # Invariant: whenever it says yes, the spend stays within the budget if the next
        # audit costs no more than the dearest so far.
        for spent in ([0.2], [0.4, 0.9, 0.3], [1.5, 1.5]):
            for budget in (1.0, 2.0, 3.5, 5.0):
                if benchmark.can_afford(spent, budget):
                    self.assertLessEqual(sum(spent) + max(spent), budget)


class TestResuming(unittest.TestCase):
    def results(self, root: Path) -> list[benchmark.VariantResult]:
        item = openai_math.Challenge("Thing", root / "S.lean", "M", root / "M.lean", ("t",), ())
        variant = benchmark.Variant(item, None, root / "S.lean", None, None)
        rows = [
            row("differs", (3, 4)),
            row("not in the formalization", None),
            VerdictRow("conclusion", "p ↔ q", "p → q", MATCHES, False, (9, 9), ("E2", "E5")),
        ]
        return [benchmark.VariantResult(variant, rows, 0.4321, False, "a" * 64)]

    def test_saved_results_read_back_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            saved = self.results(out)
            benchmark.save_results(out, {"Thing": saved})
            back = benchmark.earlier_results(out)[("Thing", benchmark.CONTROL)]
            self.assertEqual(back.rows, saved[0].rows)
            self.assertEqual(
                (back.copy_sha256, back.cost_usd, back.hit_round_limit), ("a" * 64, 0.4321, False)
            )

    def test_only_an_identical_copy_reuses_an_audit(self) -> None:
        before = benchmark.EarlierResult("a" * 64, [], 1.0, False)
        self.assertTrue(benchmark.reusable(before, "a" * 64))
        self.assertFalse(benchmark.reusable(before, "b" * 64))

    def test_an_incomplete_results_file_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            self.assertEqual(benchmark.earlier_results(out), {})
            benchmark.save_results(out, {"Thing": self.results(out)})
            path = out / benchmark.RESULTS_FILE
            good = json.loads(path.read_text(encoding="utf-8"))
            for damage in ("copy_sha256", "rows"):
                broken = json.loads(json.dumps(good))
                del broken["Thing"][0][damage]
                path.write_text(json.dumps(broken), encoding="utf-8")
                with self.subTest(damage), self.assertRaisesRegex(BenchmarkError, "complete"):
                    benchmark.earlier_results(out)
            for field_name, value in (("verdict", "fine"), ("lean_lines", [3])):
                broken = json.loads(json.dumps(good))
                broken["Thing"][0]["rows"][0][field_name] = value
                path.write_text(json.dumps(broken), encoding="utf-8")
                with self.subTest(field_name), self.assertRaisesRegex(BenchmarkError, "complete"):
                    benchmark.earlier_results(out)


class TestBlindness(unittest.TestCase):
    """Nothing the helper is given may say which copy it is auditing."""

    def test_copies_look_the_same_to_the_helper(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "lean-toolchain").write_text("leanprover/lean4:v4.34.1\n", encoding="utf-8")
            ws = LeanWorkspace(root=root, lake=root / "lake", exporter=root / "exp")
            item = openai_math.Challenge(
                name="TruffetCounterexample",
                statement_file=root / "S.lean",
                solution_module="OAI.Some.Module",
                solution_file=root / "M.lean",
                theorem_names=("OAI.TruffetV4Counterexample.finite_execution_not_optimal",),
                permitted_axioms=(),
            )
            prompts, tools = [], []
            for variant in (benchmark.CONTROL, "one-direction"):
                path = copy_folder(ws, item.name, variant) / "TruffetCounterexample.lean"
                self.assertNotIn(variant, str(path.relative_to(root)))
                self.assertRegex(path.parent.name, r"^[0-9a-f]{16}$")
                path.parent.mkdir(parents=True)
                path.write_text("x\n", encoding="utf-8")
                report = report_from_json(raw("truffet_challenge"), "S.lean", EVIDENCE)
                box = StatementToolbox(
                    workspace=ws,
                    statement_file=path,
                    solution_module=item.solution_module,
                    reports={item.theorem_names[0]: report},
                    paper_files=[],
                    claim_preamble="import Mathlib",
                    claim_note=COPY_CLAIM_NOTE,
                    proof_note=COPY_PROOF_NOTE,
                    claims_folder=path.parent / "claims",
                )
                prompts.append(
                    audit_prompt(box, item, ("Paper",), COPY_STATUS).replace(
                        path.parent.name, "<copy>"
                    )
                )
                tools.append(json.dumps(box.definitions(), sort_keys=True))
                statement = box.run("read_statement", {"theorem": item.theorem_names[0]})
                self.assertIn(COPY_PROOF_NOTE, statement.result)
            self.assertEqual(prompts[0], prompts[1])
            self.assertEqual(tools[0], tools[1])
            for word in ("plant", "benchmark", "control"):
                self.assertNotIn(word, prompts[0].lower())
                self.assertNotIn(word, tools[0].lower())


if __name__ == "__main__":
    unittest.main()
