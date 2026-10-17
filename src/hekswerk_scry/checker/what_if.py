"""What-If tests at the wiring level: remove something, see what loses a fact it needs.

This answers "which steps rely on this?" honestly. It does not answer "is this step
mathematically necessary?": that needs Lean to re-check the changed proof.
"""

from dataclasses import replace

from hekswerk_scry.checker.wiring import WiringReport, check_wiring
from hekswerk_scry.core.enums import CheckKind, ProblemKind, StepStatus, WhatIfKind
from hekswerk_scry.models.proof_map import ProofMap
from hekswerk_scry.models.what_if import BreakageReport, StepBreakage, WhatIfChange

WIRING_WHAT_IF_CAVEAT = (
    "This is a wiring test. It shows which steps lose a fact they rely on. It does not "
    "check whether any step's math is correct, and a step that nothing relies on is not "
    "necessarily pointless. Answering those questions needs a Lean check."
)


def run_what_if(proof_map: ProofMap, change: WhatIfChange) -> BreakageReport:
    """Apply `change` to a copy of `proof_map` and report which steps break."""
    before = check_wiring(proof_map)
    if any(problem.kind is ProblemKind.LOOP for problem in before.map_problems):
        raise ValueError(
            "Can't run a What-If test on a map that has a loop. Fix the loop first."
        )
    changed_map = _apply_change(proof_map, change)
    after = check_wiring(changed_map)

    broken = _newly_broken(changed_map, before, after)
    already_broken = tuple(
        step_id
        for step_id, verdict in before.verdicts.items()
        if verdict.status is not StepStatus.WIRING_CHECKED and step_id in changed_map.steps
    )
    headline, explanation = _describe(change, broken, before.goal_reached, after.goal_reached)
    return BreakageReport(
        change=change,
        checked_by=CheckKind.WIRING,
        broken_steps=broken,
        already_broken_step_ids=already_broken,
        goal_reached_before=before.goal_reached,
        goal_reached_after=after.goal_reached,
        headline=headline,
        explanation=explanation,
        caveat=WIRING_WHAT_IF_CAVEAT,
    )


def _apply_change(proof_map: ProofMap, change: WhatIfChange) -> ProofMap:
    if change.kind is WhatIfKind.REMOVE_STEP:
        if change.target not in proof_map.steps:
            raise ValueError(f"There is no step '{change.target}' in this map.")
        # Remove the step and the arrows pointing at it, so the steps that relied on it
        # report the fact they are now missing.
        remaining = {
            step_id: replace(
                step, depends_on=tuple(d for d in step.depends_on if d != change.target)
            )
            for step_id, step in proof_map.steps.items()
            if step_id != change.target
        }
        return proof_map.with_steps(remaining)

    if change.target not in proof_map.starting_facts:
        listed = ", ".join(f"'{fact}'" for fact in proof_map.starting_facts) or "none"
        raise ValueError(
            f"'{change.target}' is not one of this map's starting facts. "
            f"The starting facts are: {listed}."
        )
    return replace(
        proof_map,
        starting_facts=tuple(f for f in proof_map.starting_facts if f != change.target),
    )


def _newly_broken(
    changed_map: ProofMap, before: WiringReport, after: WiringReport
) -> tuple[StepBreakage, ...]:
    """Steps that lined up before the change and don't after it, nearest first."""
    distance: dict[str, int] = {}
    broken: list[StepBreakage] = []
    for step_id in changed_map.topological_order():
        was = before.verdicts[step_id].status
        now = after.verdicts[step_id]
        if was is not StepStatus.WIRING_CHECKED or now.status is StepStatus.WIRING_CHECKED:
            continue
        hit_directly = any(p.kind is not ProblemKind.DEPENDENCY_BROKEN for p in now.problems)
        if hit_directly:
            distance[step_id] = 1
        else:
            parents = changed_map.steps[step_id].depends_on
            distance[step_id] = 1 + min((distance[p] for p in parents if p in distance), default=0)
        broken.append(
            StepBreakage(
                step_id=step_id,
                step_title=changed_map.steps[step_id].title,
                steps_away=distance[step_id],
                hit_directly=hit_directly,
                reasons=tuple(problem.message for problem in now.problems),
            )
        )
    broken.sort(key=lambda item: item.steps_away)
    return tuple(broken)


def _describe(
    change: WhatIfChange,
    broken: tuple[StepBreakage, ...],
    goal_before: bool,
    goal_after: bool,
) -> tuple[str, str]:
    what = change.describe()
    goal_lost = goal_before and not goal_after
    if not broken and not goal_lost:
        return (
            f"Nothing relies on this: after {what}, every step that lined up still does.",
            "No step loses a fact it needs.",
        )
    if not broken:
        return (
            f"After {what}, the goal is no longer reached.",
            "No other step loses a fact, but the step that proved the goal is gone.",
        )
    first = broken[0]
    headline = (
        f"{what[0].upper()}{what[1:]} breaks {len(broken)} step(s), starting with "
        f"'{first.step_title}' ({first.step_id})."
    )
    if goal_lost:
        headline += " The goal is no longer reached."
    lines = [
        f"'{item.step_title}' ({item.step_id}), {item.steps_away} step(s) away: "
        + " ".join(item.reasons)
        for item in broken
    ]
    return headline, "\n".join(lines)
