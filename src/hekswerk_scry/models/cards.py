"""Simplification cards: proposals to swap a group of steps for a shorter route."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Self

from hekswerk_scry.core.hashing import fingerprint_data
from hekswerk_scry.models.proof_map import ProofMap, ProofStep


@dataclass(frozen=True)
class SimplificationCard:
    """A proposal to replace a group of steps with a shorter route.

    The rule for a swap: the replacement may only assume facts the original group took
    from outside (its inputs) or the map's starting facts, and it must prove every fact
    the rest of the proof takes from the group (its outputs). Those inputs and outputs
    are worked out from the map itself when the card is checked; the card can't declare
    its own.

    The card also remembers a fingerprint of every step it replaces, taken when it was
    drafted. If any of those steps change afterwards, the card is stale.
    """

    card_id: str
    title: str
    why: str
    region_step_ids: tuple[str, ...]
    region_fingerprints: tuple[tuple[str, str], ...]
    replacement_steps: tuple[ProofStep, ...]

    @classmethod
    def draft(
        cls,
        proof_map: ProofMap,
        *,
        card_id: str,
        title: str,
        why: str,
        region_step_ids: Iterable[str],
        replacement_steps: Iterable[ProofStep],
    ) -> Self:
        """Draft a card against the current contents of `proof_map`."""
        region = tuple(dict.fromkeys(region_step_ids))
        if not region:
            raise ValueError(f"Card '{card_id}' must name at least one step to replace.")
        missing = [step_id for step_id in region if step_id not in proof_map.steps]
        if missing:
            raise ValueError(
                f"Can't draft card '{card_id}': these steps are not in the map: "
                f"{', '.join(missing)}."
            )
        return cls(
            card_id=card_id,
            title=title,
            why=why,
            region_step_ids=region,
            region_fingerprints=tuple(
                (step_id, proof_map.steps[step_id].fingerprint()) for step_id in region
            ),
            replacement_steps=tuple(replacement_steps),
        )

    def fingerprint(self) -> str:
        return fingerprint_data(
            {
                "card_id": self.card_id,
                "region_fingerprints": [list(pair) for pair in self.region_fingerprints],
                "replacement_steps": [step.fingerprint() for step in self.replacement_steps],
            }
        )
