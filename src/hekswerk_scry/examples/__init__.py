"""Example proof maps that ship with Scry."""

import json
from importlib import resources

from hekswerk_scry.files import proof_map_from_dict
from hekswerk_scry.models.proof_map import ProofMap


def load_example(name: str) -> ProofMap:
    """Load a bundled example, for instance `load_example("shifted_fraction")`."""
    path = resources.files("hekswerk_scry.examples").joinpath(f"{name}.json")
    if not path.is_file():
        raise ValueError(f"There is no bundled example called '{name}'.")
    return proof_map_from_dict(
        json.loads(path.read_text(encoding="utf-8")), source=f"Example '{name}'"
    )
