"""The edges of a group of steps: what it takes in and what it hands on.

Both the Knot finder and Simplification cards need to know, for a group of steps,
which facts the group gets from outside (its inputs) and which facts the rest of the
proof gets from the group (its outputs). A group can be swapped for any other route
with the same inputs and outputs without the rest of the proof noticing.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from hekswerk_scry.models.proof_map import ProofMap


@dataclass(frozen=True)
class RegionBoundary:
    """What a group of steps needs from outside and what it provides to the rest."""

    step_ids: tuple[str, ...]
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]


def region_boundary(proof_map: ProofMap, step_ids: Iterable[str]) -> RegionBoundary:
    """Work out the inputs and outputs of the group `step_ids` within `proof_map`.

    - inputs: facts assumed by steps in the group but not proved inside the group.
    - outputs: facts proved inside the group that a step outside the group takes from
      it, plus the goal if the goal step is inside the group.
    """
    region = set(step_ids)
    if not region:
        raise ValueError("A group of steps must contain at least one step.")
    unknown = sorted(region - set(proof_map.steps))
    if unknown:
        raise ValueError(f"These steps are not in the proof map: {', '.join(unknown)}.")

    order = proof_map.topological_order()
    inside = [step_id for step_id in order if step_id in region]
    proved_inside = {proof_map.steps[step_id].contract.proves for step_id in inside}

    inputs: dict[str, None] = {}
    for step_id in inside:
        for fact in proof_map.steps[step_id].contract.assumes:
            if fact not in proved_inside:
                inputs[fact] = None

    outputs: dict[str, None] = {}
    for step_id in order:
        if step_id in region:
            continue
        step = proof_map.steps[step_id]
        for dep in step.depends_on:
            if dep in region and proof_map.steps[dep].contract.proves in step.contract.assumes:
                outputs[proof_map.steps[dep].contract.proves] = None
    if proof_map.goal_step_id in region:
        outputs[proof_map.goal] = None

    return RegionBoundary(step_ids=tuple(inside), inputs=tuple(inputs), outputs=tuple(outputs))
