"""Outlines: a result and the theorems and definitions of its project that it rests on.

Built from real exporter output (`fixtures/outline_example.lean-outline.json`, made by
`scry-export --outline` on `fixtures/lean/Outline.lean`), and from made-up graphs.
"""

import json
import random
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from hekswerk_scry.files import (
    MapFileError,
    load_outline,
    outline_from_dict,
    outline_to_dict,
    save_outline,
)
from hekswerk_scry.lean.outline import _without_doc_comment, changed_files, outline_from_lean
from hekswerk_scry.lean.workspace import LeanWorkspace
from hekswerk_scry.models.outline import Outline, OutlineError, OutlinePart, _closures

FIXTURES = Path(__file__).parent / "fixtures"
NS = "OutlineExample."


def exporter_output() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        (FIXTURES / "outline_example.lean-outline.json").read_text(encoding="utf-8"))
    return data


def example_outline(project: Path) -> Outline:
    """The fixture's outline, as if made in a Lean project at `project`."""
    (project / "Examples").mkdir(parents=True, exist_ok=True)
    lean_file = project / "Examples" / "Outline.lean"
    shutil.copy(FIXTURES / "lean" / "Outline.lean", lean_file)
    workspace = LeanWorkspace(root=project, lake=project / "lake", exporter=project / "export")
    return outline_from_lean(exporter_output(), workspace, lean_file)


def part(part_id: str, kind: str = "theorem", statement_uses: tuple[str, ...] = (),
         body_uses: tuple[str, ...] = ()) -> OutlinePart:
    return OutlinePart(part_id=part_id, name=part_id, kind=kind, private=False, module=None,
                       file=None, start_line=None, end_line=None, doc=None, statement="T",
                       source=None, statement_uses=statement_uses, body_uses=body_uses)


class ExampleCase(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.project = Path(folder.name)
        self.outline = example_outline(self.project)

    def get(self, name: str) -> OutlinePart:
        [found] = [p for p in self.outline.parts.values() if p.name == NS + name]
        return found


class TestFromLean(ExampleCase):
    def test_the_parts_are_the_declarations_a_person_wrote(self) -> None:
        names = {p.name.removeprefix(NS) for p in self.outline.parts.values()}
        self.assertEqual(names, {"result", "parity", "swap", "double", "Loose", "Pt",
                                 "pts_differ", "swap_swap", "loose", "double_eq",
                                 "instDecidableEqPt"})
        self.assertEqual(next(iter(self.outline.parts)), NS + "result")

    def test_helpers_lean_made_are_looked_through(self) -> None:
        # `decide` on `Pt` goes through the derived instance and the constructor's
        # helpers; only the instance (written where `deriving` is) and `Pt` remain.
        self.assertEqual(set(self.get("pts_differ").body_uses),
                         {NS + "Pt", NS + "instDecidableEqPt"})
        instance = self.get("instDecidableEqPt")
        self.assertEqual(instance.kind, "instance")
        self.assertEqual(instance.source, "  deriving DecidableEq")
        self.assertEqual(self.get("Pt").kind, "structure")

    def test_a_private_declaration_is_shown_by_its_written_name(self) -> None:
        double = self.get("double")
        self.assertTrue(double.private)
        self.assertTrue(double.part_id.startswith("_private."))
        self.assertIn(double.part_id, self.get("double_eq").statement_uses)

    def test_only_the_statement_s_own_hypotheses_count_as_unused(self) -> None:
        found = {p.name.removeprefix(NS): [(h.name, h.statement) for h in p.unused_hypotheses]
                 for p in self.outline.parts.values() if p.unused_hypotheses}
        # `loose` ignores a hypothesis too, but it is written inside the definition `Loose`.
        self.assertEqual(found, {"result": [("_spare", "n ≠ 7"), (None, "m ≠ 3")]})

    def test_each_part_carries_the_text_it_is_written_as(self) -> None:
        lines = (FIXTURES / "lean" / "Outline.lean").read_text(encoding="utf-8").splitlines()
        for p in self.outline.parts.values():
            assert p.start_line is not None and p.end_line is not None
            self.assertEqual(p.source, "\n".join(lines[p.start_line - 1:p.end_line]))
            self.assertEqual(p.file, "Examples/Outline.lean")
        self.assertEqual(self.get("swap").source, "def swap (p : Pt) : Pt := ⟨p.y, p.x⟩")
        self.assertEqual(self.get("Pt").doc, "A point with two whole-number coordinates.")

    def test_a_doc_comment_is_not_part_of_the_text_on_either_lean_version(self) -> None:
        # Lean v4.34 places a declaration from its doc comment on; v4.10 from after it.
        data = exporter_output()
        [pt] = [p for p in data["parts"] if p["id"] == NS + "Pt"]
        pt["start"]["line"] -= 1
        workspace = LeanWorkspace(self.project, self.project / "lake", self.project / "export")
        outline = outline_from_lean(data, workspace, self.project / "Examples" / "Outline.lean")
        as_v434, as_v410 = outline.parts[NS + "Pt"], self.get("Pt")
        self.assertEqual((as_v434.source, as_v434.start_line),
                         (as_v410.source, as_v410.start_line))
        self.assertEqual(_without_doc_comment(["/-- Two. -/ def two := 2", "x"], 1, 2),
                         (1, "def two := 2\nx"))
        self.assertEqual(_without_doc_comment(["/-- Two,", "  said twice. -/", "def two :=", " 2"],
                                              1, 4), (3, "def two :=\n 2"))

    def test_reading_the_claim_needs_definitions_not_proofs(self) -> None:
        self.assertEqual({c.removeprefix(NS) for c in self.outline.claim()},
                         {"parity", "swap", "Loose", "Pt", self.get("double").part_id})

    def test_a_changed_or_missing_file_is_noticed(self) -> None:
        self.assertEqual(changed_files(self.outline), [])
        lean_file = self.project / "Examples" / "Outline.lean"
        lean_file.write_text(lean_file.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        self.assertEqual(changed_files(self.outline), ["Examples/Outline.lean"])
        lean_file.unlink()
        self.assertEqual(changed_files(self.outline), ["Examples/Outline.lean"])

    def test_a_module_s_file_is_found_in_the_project_or_its_packages(self) -> None:
        data = exporter_output()
        data["parts"][1]["module"] = "Dep.Thing"  # parity
        package = self.project / ".lake" / "packages" / "dep" / "Dep"
        package.mkdir(parents=True)
        (package / "Thing.lean").write_text("x\n" * 40, encoding="utf-8")
        workspace = LeanWorkspace(self.project, self.project / "lake", self.project / "export")
        outline = outline_from_lean(data, workspace, self.project / "Examples" / "Outline.lean")
        parity = outline.parts[NS + "parity"]
        self.assertEqual(parity.file, ".lake/packages/dep/Dep/Thing.lean")
        self.assertEqual(parity.source, "x\nx\nx")
        self.assertIn(parity.file, outline.file_sha256)


class TestFiles(ExampleCase):
    def test_saved_and_loaded_it_is_the_same(self) -> None:
        path = self.project / "x.outline.json"
        save_outline(self.outline, path)
        self.assertEqual(load_outline(path), self.outline)

    def test_anything_unexpected_is_refused(self) -> None:
        good = outline_to_dict(self.outline)

        def broken(change: Any) -> dict[str, Any]:
            data: dict[str, Any] = json.loads(json.dumps(good))
            change(data)
            return data

        cases = {
            "field(s) Scry doesn't recognise: colour": lambda d: d["parts"][0].update(colour=1),
            "missing: kind": lambda d: d["parts"][0].pop("kind"),
            "format 'hekswerk-scry/proof-map'":
                lambda d: d.update(format="hekswerk-scry/proof-map"),
            "listed more than once": lambda d: d["parts"].append(d["parts"][3]),
            "'private' should be true or false": lambda d: d["parts"][2].update(private="no"),
            "isn't in the outline": lambda d: d["parts"].pop(),
            "must be its result": lambda d: d["parts"].reverse(),
            "has no fingerprint": lambda d: d["file_sha256"].clear(),
        }
        for words, change in cases.items():
            with self.subTest(words), self.assertRaises(MapFileError) as caught:
                outline_from_dict(broken(change))
            self.assertIn(words, str(caught.exception))


class TestReading(unittest.TestCase):
    def test_what_rests_on_what_matches_following_every_route(self) -> None:
        rng = random.Random(5)
        for trial in range(200):
            nodes = [f"n{i}" for i in range(rng.randint(1, 14))]
            edges = {n: rng.sample(nodes, rng.randint(0, min(4, len(nodes)))) for n in nodes}
            expected = {}
            for n in nodes:
                seen: set[str] = set()
                todo = list(edges[n])
                while todo:
                    m = todo.pop()
                    if m not in seen:
                        seen.add(m)
                        todo.extend(edges[m])
                expected[n] = frozenset(seen - {n})
            self.assertEqual(_closures(edges), expected, (trial, edges))

    def test_used_by_is_uses_turned_round(self) -> None:
        outline = Outline("r", "/p", "v", {}, (), {
            "r": part("r", statement_uses=("d",), body_uses=("t", "d")),
            "t": part("t", body_uses=("d",)),
            "d": part("d", kind="definition"),
        })
        self.assertEqual(outline.used_by(), {"r": (), "t": ("r",), "d": ("r", "t")})

    def test_the_claim_follows_definitions_but_not_proofs(self) -> None:
        outline = Outline("r", "/p", "v", {}, (), {
            "r": part("r", statement_uses=("d", "t"), body_uses=("t", "e")),
            "d": part("d", kind="definition", body_uses=("s",), statement_uses=("ty",)),
            "s": part("s", kind="structure"),
            "ty": part("ty", kind="definition"),
            "t": part("t", statement_uses=("u",), body_uses=("v",)),
            "u": part("u", kind="definition"),
            "v": part("v", kind="definition"),
            "e": part("e", kind="definition"),
        })
        self.assertEqual(outline.claim(), ("d", "t", "ty", "s", "u"))

    def test_an_outline_that_doesn_t_hang_together_is_refused(self) -> None:
        with self.assertRaises(OutlineError):
            Outline("r", "/p", "v", {}, (), {"r": part("r", body_uses=("gone",))})
        with self.assertRaises(OutlineError):
            Outline("r", "/p", "v", {}, (), {"x": part("x"), "r": part("r")})


if __name__ == "__main__":
    unittest.main()
