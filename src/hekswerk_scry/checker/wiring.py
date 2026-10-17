"""The built-in wiring check.

It answers one question: do the facts feed into each other correctly? For every step
it confirms that each fact the step assumes is either a starting fact or is proved by
a step it lists as a dependency. It also checks the map as a whole: the goal step
exists, it proves the stated goal, and the goal isn't simply assumed at the start.

It never reads a step's math, code, or English. Passing it means "wiring checked
(not proven)", never "proven". Only a Lean check can say a step is proven.
"""

from dataclasses import dataclass

from hekswerk_scry.core.enums import CheckKind, ProblemKind, StepStatus
from hekswerk_scry.models.proof_map import DependencyLoopError, ProofMap, ProofStep
from hekswerk_scry.models.receipts import Receipt


@dataclass(frozen=True)
class WiringProblem:
    """One thing that doesn't line up, explained in plain English."""

    kind: ProblemKind
    message: str


@dataclass(frozen=True)
class StepVerdict:
    """The wiring check's result for one step.

    `notes` are worth a look but don't count as problems, such as an arrow to a step
    whose fact is never used.
    """

    step_id: str
    status: StepStatus
    problems: tuple[WiringProblem, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class WiringReport:
    """The wiring check's result for a whole map."""

    map_fingerprint: str
    verdicts: dict[str, StepVerdict]
    map_problems: tuple[WiringProblem, ...]
    goal_reached: bool
    summary: str
    receipt: Receipt

    @property
    def passed(self) -> bool:
        return self.receipt.passed

    def broken_step_ids(self) -> tuple[str, ...]:
        return tuple(
            step_id
            for step_id, verdict in self.verdicts.items()
            if verdict.status is StepStatus.WIRING_BROKEN
        )


def check_wiring(proof_map: ProofMap) -> WiringReport:
    """Run the wiring check over every step of `proof_map`."""
    map_problems = _goal_problems(proof_map)
    try:
        order = proof_map.topological_order()
    except DependencyLoopError as exc:
        map_problems.append(WiringProblem(ProblemKind.LOOP, str(exc)))
        note = "Not checked: the map has a loop, so there is no order to check the steps in."
        verdicts = {
            step_id: StepVerdict(step_id, StepStatus.NOT_CHECKED, notes=(note,))
            for step_id in sorted(proof_map.steps)
        }
        return _finish(proof_map, verdicts, map_problems)

    starting = set(proof_map.starting_facts)
    verdicts = {}
    for step_id in order:
        verdicts[step_id] = _check_step(proof_map, proof_map.steps[step_id], starting, verdicts)
    return _finish(proof_map, verdicts, map_problems)


def _goal_problems(proof_map: ProofMap) -> list[WiringProblem]:
    problems: list[WiringProblem] = []
    goal_step = proof_map.steps.get(proof_map.goal_step_id)
    if goal_step is None:
        problems.append(
            WiringProblem(
                ProblemKind.GOAL_STEP_MISSING,
                f"The goal is supposed to be proved by step '{proof_map.goal_step_id}', "
                "but there is no step with that ID.",
            )
        )
    elif goal_step.contract.proves != proof_map.goal:
        problems.append(
            WiringProblem(
                ProblemKind.GOAL_STEP_PROVES_SOMETHING_ELSE,
                f"The goal is '{proof_map.goal}', but the goal step "
                f"'{proof_map.goal_step_id}' proves '{goal_step.contract.proves}' instead.",
            )
        )
    if proof_map.goal in proof_map.starting_facts:
        problems.append(
            WiringProblem(
                ProblemKind.GOAL_IS_A_STARTING_FACT,
                f"The goal '{proof_map.goal}' is also listed as a starting fact, so the proof "
                "would be assuming exactly what it sets out to prove.",
            )
        )
    return problems


def _check_step(
    proof_map: ProofMap,
    step: ProofStep,
    starting: set[str],
    earlier: dict[str, StepVerdict],
) -> StepVerdict:
    problems: list[WiringProblem] = []
    known_deps: list[str] = []
    for dep in step.depends_on:
        if dep in proof_map.steps:
            known_deps.append(dep)
        else:
            problems.append(
                WiringProblem(
                    ProblemKind.UNKNOWN_DEPENDENCY,
                    f"Lists '{dep}' as a step it depends on, but there is no step with that ID.",
                )
            )

    for fact in step.contract.assumes:
        if fact == step.contract.proves:
            problems.append(
                WiringProblem(
                    ProblemKind.USES_OWN_CONCLUSION,
                    f"Assumes '{fact}', which is the very fact it claims to prove.",
                )
            )
            continue
        if fact in starting:
            continue
        providers = [dep for dep in known_deps if proof_map.steps[dep].contract.proves == fact]
        if providers:
            if all(earlier[dep].status is not StepStatus.WIRING_CHECKED for dep in providers):
                problems.append(
                    WiringProblem(
                        ProblemKind.DEPENDENCY_BROKEN,
                        f"Needs '{fact}' from step '{providers[0]}', but that step has "
                        "wiring problems of its own.",
                    )
                )
            continue
        elsewhere = [sid for sid in proof_map.steps_proving(fact) if sid != step.step_id]
        if elsewhere:
            problems.append(
                WiringProblem(
                    ProblemKind.FROM_UNLISTED_STEP,
                    f"Needs '{fact}'. Step '{elsewhere[0]}' proves it, but this step does not "
                    f"list '{elsewhere[0]}' as a step it depends on.",
                )
            )
        else:
            problems.append(
                WiringProblem(
                    ProblemKind.FACT_NOT_PROVIDED,
                    f"Needs '{fact}', but that is not a starting fact and no step it depends "
                    "on proves it.",
                )
            )

    notes = tuple(
        f"Lists step '{dep}' as a dependency but never uses what it proves "
        f"('{proof_map.steps[dep].contract.proves}')."
        for dep in known_deps
        if proof_map.steps[dep].contract.proves not in step.contract.assumes
    )
    status = StepStatus.WIRING_BROKEN if problems else StepStatus.WIRING_CHECKED
    return StepVerdict(step.step_id, status, tuple(problems), notes)


def _finish(
    proof_map: ProofMap,
    verdicts: dict[str, StepVerdict],
    map_problems: list[WiringProblem],
) -> WiringReport:
    broken = [
        sid for sid, verdict in verdicts.items() if verdict.status is not StepStatus.WIRING_CHECKED
    ]
    passed = not map_problems and not broken
    goal_verdict = verdicts.get(proof_map.goal_step_id)
    # The goal can still be reached when some unrelated step is broken.
    goal_reached = (
        not map_problems
        and goal_verdict is not None
        and goal_verdict.status is StepStatus.WIRING_CHECKED
    )
    total = len(verdicts)
    if passed:
        summary = (
            f"Wiring checked (not proven): all {total} steps line up and the goal is reached. "
            "This check only follows which facts feed into which steps. It does not read "
            "the math or the code, so nothing here is proven yet."
        )
    else:
        parts: list[str] = []
        if map_problems:
            parts.append(f"{len(map_problems)} problem(s) with the map as a whole")
        broken_now = [sid for sid in broken if verdicts[sid].status is StepStatus.WIRING_BROKEN]
        if broken_now:
            parts.append(
                f"{len(broken_now)} of {total} step(s) don't line up ({', '.join(broken_now)})"
            )
        summary = "Wiring broken: " + "; ".join(parts) + "."
    fingerprint = proof_map.fingerprint()
    receipt = Receipt.create(
        checked_by=CheckKind.WIRING,
        subject=f"proof map '{proof_map.map_id}'",
        subject_fingerprint=fingerprint,
        passed=passed,
        summary=summary,
    )
    return WiringReport(
        map_fingerprint=fingerprint,
        verdicts=verdicts,
        map_problems=tuple(map_problems),
        goal_reached=goal_reached,
        summary=summary,
        receipt=receipt,
    )
