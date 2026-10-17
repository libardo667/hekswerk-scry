"""The scanner: finds where to look first in a proof.

It looks only at the shape of the proof (which steps feed which) and reports:

- Chokepoints: steps that every route from the starting facts to the goal passes
  through. They are the spine of the proof.
- Knots: groups of steps that only exist to produce one result. Every route from any
  step in the group to the goal passes through the group's last step, so nothing else
  uses the group's in-between results. A Knot can be swapped for a shorter route with
  the same inputs and the same result.
- Unused steps: steps that don't lead to the goal at all.

The scanner does not judge whether any step is correct.
"""

from dataclasses import dataclass

from hekswerk_scry.checker.regions import region_boundary
from hekswerk_scry.models.proof_map import ProofMap


@dataclass(frozen=True)
class Chokepoint:
    """A step that every route to the goal passes through."""

    step_id: str
    step_title: str
    proves: str
    feeding_step_count: int
    explanation: str


@dataclass(frozen=True)
class Knot:
    """A group of steps that only exists to produce one result."""

    knot_id: str
    exit_step_id: str
    step_ids: tuple[str, ...]
    inputs: tuple[str, ...]
    output: str
    explanation: str


@dataclass(frozen=True)
class UnusedStep:
    """A step that does not lead to the goal."""

    step_id: str
    step_title: str
    explanation: str


@dataclass(frozen=True)
class MapScan:
    """Everything the scanner found in one map."""

    map_id: str
    step_count: int
    chokepoints: tuple[Chokepoint, ...]
    knots: tuple[Knot, ...]
    unused_steps: tuple[UnusedStep, ...]
    overview: str


def scan_proof_map(proof_map: ProofMap, *, min_knot_steps: int = 3) -> MapScan:
    """Find the Chokepoints, Knots, and unused steps in `proof_map`."""
    goal = proof_map.goal_step_id
    if goal not in proof_map.steps:
        raise ValueError(f"Can't scan this map: its goal step '{goal}' is not in the map.")
    order = proof_map.topological_order()
    useful = proof_map.ancestors_of(goal) | {goal}
    useful_order = [step_id for step_id in order if step_id in useful]

    chokepoints = _find_chokepoints(proof_map, useful_order, useful)
    knots = _find_knots(proof_map, useful_order, useful, chokepoints, min_knot_steps)
    unused = tuple(
        UnusedStep(
            step_id=step_id,
            step_title=proof_map.steps[step_id].title,
            explanation=_unused_explanation(proof_map, step_id),
        )
        for step_id in order
        if step_id not in useful
    )

    overview = (
        f"'{proof_map.title}' has {len(order)} step(s). Found {len(chokepoints)} chokepoint(s) "
        f"(steps every route to the goal passes through), {len(knots)} knot(s) (groups of "
        "steps that only exist to produce one result), and "
        f"{len(unused)} unused step(s) (steps that don't lead to the goal). This scan only "
        "looks at which steps feed which; it does not judge whether any step is correct."
    )
    return MapScan(
        map_id=proof_map.map_id,
        step_count=len(order),
        chokepoints=chokepoints,
        knots=knots,
        unused_steps=unused,
        overview=overview,
    )


def _unused_explanation(proof_map: ProofMap, step_id: str) -> str:
    proves = proof_map.steps[step_id].contract.proves
    if proof_map.lean_source is not None:
        return (
            f"Lean's finished proof doesn't rely on what this step proves ('{proves}'). The "
            "code may still need it in order to compile (for example, a hint another tactic "
            "was given but didn't use). A Lean What-If test can tell."
        )
    return (
        f"Nothing on the way to the goal uses what this step proves ('{proves}'). It may be "
        "leftover searching, or the map may be missing an arrow."
    )


def _find_chokepoints(
    proof_map: ProofMap, useful_order: list[str], useful: set[str]
) -> tuple[Chokepoint, ...]:
    # For each step, collect the steps that every route from the starting facts to it
    # must pass through (its "dominators"). Steps with no dependencies are reached
    # straight from the starting facts, so only they themselves are unavoidable.
    must_pass: dict[str, set[str]] = {}
    for step_id in useful_order:
        parents = [dep for dep in proof_map.steps[step_id].depends_on if dep in useful]
        common = set.intersection(*(must_pass[p] for p in parents)) if parents else set()
        must_pass[step_id] = common | {step_id}

    goal = proof_map.goal_step_id
    found: list[Chokepoint] = []
    for step_id in useful_order:
        if step_id == goal or step_id not in must_pass[goal]:
            continue
        step = proof_map.steps[step_id]
        feeding = len(proof_map.ancestors_of(step_id))
        found.append(
            Chokepoint(
                step_id=step_id,
                step_title=step.title,
                proves=step.contract.proves,
                feeding_step_count=feeding,
                explanation=(
                    "Every route from the starting facts to the goal passes through this "
                    f"step, so '{step.contract.proves}' is how the earlier part of the proof "
                    f"connects to the later part. {feeding} earlier step(s) feed into it."
                ),
            )
        )
    return tuple(found)


def _find_knots(
    proof_map: ProofMap,
    useful_order: list[str],
    useful: set[str],
    chokepoints: tuple[Chokepoint, ...],
    min_knot_steps: int,
) -> tuple[Knot, ...]:
    # For each step, collect the steps that every route from it to the goal must pass
    # through (its "post-dominators"). Working backwards from the goal makes this one
    # pass, because every useful step other than the goal has a useful child.
    goal = proof_map.goal_step_id
    children = proof_map.children()
    leads_through: dict[str, set[str]] = {}
    for step_id in reversed(useful_order):
        kids = [kid for kid in children[step_id] if kid in useful]
        if step_id == goal or not kids:
            leads_through[step_id] = {step_id}
        else:
            leads_through[step_id] = set.intersection(*(leads_through[k] for k in kids)) | {
                step_id
            }

    # A Knot ending at step X is every step whose routes to the goal all pass through X.
    # Groups ending at a Chokepoint are skipped: those are the spine, not a detour.
    skip = {goal} | {choke.step_id for choke in chokepoints}
    candidates: list[tuple[str, frozenset[str]]] = []
    for exit_id in useful_order:
        if exit_id in skip:
            continue
        group = frozenset(sid for sid in useful_order if exit_id in leads_through[sid])
        if len(group) >= min_knot_steps:
            candidates.append((exit_id, group))
    # Groups nest inside each other; report only the largest ones.
    largest = [
        (exit_id, group)
        for exit_id, group in candidates
        if not any(group < other for _, other in candidates)
    ]

    knots: list[Knot] = []
    for exit_id, group in largest:
        boundary = region_boundary(proof_map, group)
        output = proof_map.steps[exit_id].contract.proves
        inputs_text = (
            ", ".join(f"'{fact}'" for fact in boundary.inputs)
            if boundary.inputs
            else "no outside facts at all"
        )
        knots.append(
            Knot(
                knot_id=f"knot-{exit_id}",
                exit_step_id=exit_id,
                step_ids=boundary.step_ids,
                inputs=boundary.inputs,
                output=output,
                explanation=(
                    f"{len(group)} steps whose only purpose is to prove '{output}' from "
                    f"{inputs_text}. Nothing else in the proof uses their in-between results, "
                    "so the whole group could be swapped for a shorter route with the same "
                    "inputs and the same result."
                ),
            )
        )
    return tuple(knots)
