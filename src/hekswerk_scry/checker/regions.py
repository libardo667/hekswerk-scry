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


def proof_of(proof_map: ProofMap, step_id: str) -> tuple[str, ...]:
    """The steps that make up the proof of what `step_id` proves.

    That is `step_id` itself plus every earlier step whose results are needed only inside
    this group. Replacing the group touches nothing else that matters: no step that leads
    to the goal (or to `step_id`) relies on anything inside it except the final fact.

    Dead ends don't count when deciding this. A step that leads neither to the goal nor to
    `step_id` (an unused hint, say, or a rewritten copy of a hypothesis that nothing reads)
    can't make anything else necessary. Steps are returned in proof order.
    """
    if step_id not in proof_map.steps:
        raise ValueError(f"There is no step '{step_id}' in this map.")
    order = proof_map.topological_order()
    earlier = proof_map.ancestors_of(step_id)
    live = earlier | {step_id}
    if proof_map.goal_step_id in proof_map.steps:
        live |= proof_map.ancestors_of(proof_map.goal_step_id) | {proof_map.goal_step_id}
    children = proof_map.children()
    group = {step_id}
    # Working backwards, a step joins once every live step that uses it has joined.
    for candidate in reversed(order):
        if candidate not in earlier:
            continue
        users = [child for child in children[candidate] if child in live]
        if users and all(user in group for user in users):
            group.add(candidate)
    return tuple(sid for sid in order if sid in group)
