"""Small builders that keep the tests short and readable."""

from collections.abc import Iterable

from hekswerk_scry.examples import load_example
from hekswerk_scry.models import ProofMap, ProofStep, StepContract, StepViews


def make_step(
    step_id: str,
    proves: str,
    assumes: Iterable[str] = (),
    depends_on: Iterable[str] = (),
    views: StepViews | None = None,
) -> ProofStep:
    return ProofStep(
        step_id=step_id,
        title=f"Step {step_id}",
        contract=StepContract(assumes=tuple(assumes), proves=proves),
        views=views or StepViews(),
        depends_on=tuple(depends_on),
    )


def make_map(
    steps: Iterable[ProofStep],
    goal_step_id: str,
    starting_facts: Iterable[str] = (),
    goal: str | None = None,
) -> ProofMap:
    by_id = {step.step_id: step for step in steps}
    return ProofMap(
        map_id="test-map",
        title="Test map",
        starting_facts=tuple(starting_facts),
        goal=goal if goal is not None else by_id[goal_step_id].contract.proves,
        goal_step_id=goal_step_id,
        steps=by_id,
    )


def example() -> ProofMap:
    """The bundled 'shifted fraction' example used by the demo."""
    return load_example("shifted_fraction")


KNOT_STEPS = ("cube-positive", "cube-split", "square-positive", "shift-positive")


def direct_shift_step(step_id: str = "shift-positive-direct") -> ProofStep:
    """The honest one-step replacement for the example's knot."""
    return make_step(step_id, "x + 7 > 0", assumes=["x >= 0"])
