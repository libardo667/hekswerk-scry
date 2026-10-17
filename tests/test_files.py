"""Reading and writing proof map files."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from hekswerk_scry.checker import apply_card
from hekswerk_scry.files import (
    MapFileError,
    load_proof_map,
    proof_map_from_dict,
    proof_map_to_dict,
    save_proof_map,
)
from hekswerk_scry.models import SimplificationCard
from tests.helpers import KNOT_STEPS, direct_shift_step, example


def example_data() -> dict[str, Any]:
    return proof_map_to_dict(example())


class TestRoundTrip(unittest.TestCase):
    def test_example_survives_a_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "map.json"
            save_proof_map(example(), path)
            self.assertEqual(load_proof_map(path), example())

    def test_archive_and_history_survive_a_save_and_load(self) -> None:
        card = SimplificationCard.draft(
            example(),
            card_id="c",
            title="t",
            why="w",
            region_step_ids=KNOT_STEPS,
            replacement_steps=[direct_shift_step()],
        )
        swapped, _ = apply_card(example(), card)
        reloaded = proof_map_from_dict(json.loads(json.dumps(proof_map_to_dict(swapped))))
        self.assertEqual(reloaded, swapped)
        self.assertEqual(set(reloaded.archived_steps), set(KNOT_STEPS))


class TestBadFiles(unittest.TestCase):
    def assert_bad(self, data: object, phrase: str) -> None:
        with self.assertRaises(MapFileError) as caught:
            proof_map_from_dict(data)
        self.assertIn(phrase, str(caught.exception))

    def test_unknown_fields_are_rejected(self) -> None:
        data = example_data()
        data["status"] = "verified"
        self.assert_bad(data, "doesn't recognise: status")
        data = example_data()
        data["steps"][0]["verified"] = True
        self.assert_bad(data, "step 1 has field(s) Scry doesn't recognise: verified")

    def test_missing_fields_are_named(self) -> None:
        data = example_data()
        del data["goal"]
        self.assert_bad(data, "is missing: goal")

    def test_wrong_types_are_explained(self) -> None:
        data = example_data()
        data["steps"][0]["assumes"] = "x >= 0"
        self.assert_bad(data, "'assumes' should be a list")
        data = example_data()
        data["steps"][0]["proves"] = 5
        self.assert_bad(data, "'proves' should be text")

    def test_duplicate_step_ids_are_rejected(self) -> None:
        data = example_data()
        data["steps"].append(copy.deepcopy(data["steps"][0]))
        self.assert_bad(data, "is used more than once")

    def test_wrong_format_or_version(self) -> None:
        data = example_data()
        data["version"] = 99
        self.assert_bad(data, "reads format 'hekswerk-scry/proof-map' version 1")

    def test_model_errors_say_which_step(self) -> None:
        data = example_data()
        data["steps"][2]["proves"] = "   "
        self.assert_bad(data, "step 3: A step must prove something")

    def test_unreadable_files(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "broken.json"
            path.write_text("{ not json", encoding="utf-8")
            with self.assertRaisesRegex(MapFileError, "not valid JSON"):
                load_proof_map(path)
            with self.assertRaisesRegex(MapFileError, "Couldn't open"):
                load_proof_map(Path(folder) / "missing.json")


if __name__ == "__main__":
    unittest.main()
