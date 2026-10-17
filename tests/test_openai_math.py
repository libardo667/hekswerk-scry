"""Reading OpenAI's repository layout (a small stand-in folder; no network, no Lean)."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hekswerk_scry.lean import openai_math


def fake_repository(folder: Path) -> None:
    lean = folder / "lean"
    (lean / "ComparatorChallenges").mkdir(parents=True)
    (lean / "docs").mkdir()
    (lean / "OAI" / "Thing").mkdir(parents=True)
    (lean / "lean-toolchain").write_text("leanprover/lean4:v4.34.1\n", encoding="utf-8")
    (lean / "ComparatorChallenges" / "Thing.json").write_text(
        json.dumps(
            {
                "challenge_module": "ComparatorChallenges.Thing",
                "solution_module": "OAI.Thing.Main",
                "theorem_names": ["OAI.Thing.main"],
                "permitted_axioms": ["propext"],
            }
        ),
        encoding="utf-8",
    )
    (lean / "ComparatorChallenges" / "Thing.lean").write_text("-- statement\n", encoding="utf-8")
    (lean / "ComparatorChallenges" / "ThingSupport.json").write_text(
        json.dumps(
            {
                "solution_module": "OAI.Thing.Support",
                "theorem_names": ["OAI.Thing.helper"],
            }
        ),
        encoding="utf-8",
    )
    # A note about a different challenge whose name contains "Thing" comes first.
    (lean / "docs" / "000.md").write_text(
        "| Support | [ThingSupport.lean](../ComparatorChallenges/ThingSupport.lean) |\n",
        encoding="utf-8",
    )
    (lean / "docs" / "001.md").write_text(
        "# Thing\n\n- [Paper one](../../preprints/Paper-One-September-1-2026/paper.pdf)\n"
        "- [Paper two](../../preprints/Paper-Two-October-2-2026/paper.pdf)\n\n"
        "| Result | Comparator statement |\n| --- | --- |\n"
        "| Main | [Thing.lean](../ComparatorChallenges/Thing.lean) |\n",
        encoding="utf-8",
    )


class TestOpenAIMath(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        fake_repository(Path(self.folder.name))
        patcher = mock.patch.dict(os.environ, {"SCRY_OPENAI_MATH": self.folder.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_challenges_are_read_from_their_json(self) -> None:
        items = openai_math.challenges()
        self.assertEqual([c.name for c in items], ["Thing", "ThingSupport"])
        thing = openai_math.challenge("Thing")
        self.assertEqual(thing.theorem_names, ("OAI.Thing.main",))
        self.assertEqual(
            thing.solution_file.relative_to(openai_math.lean_project()), Path("OAI/Thing/Main.lean")
        )
        self.assertFalse(thing.is_supporting_result)
        self.assertTrue(items[1].is_supporting_result)

    def test_scope_notes_and_their_papers(self) -> None:
        note = openai_math.scope_note(openai_math.challenge("Thing"))
        assert note is not None
        self.assertEqual(note.name, "001.md")
        self.assertEqual(
            openai_math.papers_of(note), ("Paper-One-September-1-2026", "Paper-Two-October-2-2026")
        )
        support = openai_math.scope_note(openai_math.challenge("ThingSupport"))
        assert support is not None
        self.assertEqual(support.name, "000.md")

    def test_missing_things_are_explained(self) -> None:
        with self.assertRaisesRegex(openai_math.OpenAIMathError, "no comparator challenge"):
            openai_math.challenge("Nope")
        with (
            mock.patch.dict(os.environ, {"SCRY_OPENAI_MATH": "/no/such/place"}),
            self.assertRaisesRegex(openai_math.OpenAIMathError, "scry fetch-openai-math"),
        ):
            openai_math.lean_project()


if __name__ == "__main__":
    unittest.main()
