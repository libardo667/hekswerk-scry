"""What-If tests and Breakage reports."""

from dataclasses import dataclass

from hekswerk_scry.core.enums import CheckKind, WhatIfKind
from hekswerk_scry.core.facts import normalize_fact


@dataclass(frozen=True)
class WhatIfChange:
    """One change to try: remove a step, or drop one of the starting facts."""

    kind: WhatIfKind
    target: str

    def __post_init__(self) -> None:
        cleaned = (
            normalize_fact(self.target)
            if self.kind is WhatIfKind.DROP_STARTING_FACT
            else self.target.strip()
        )
        if not cleaned:
            raise ValueError("A What-If change needs a target (a step ID or a starting fact).")
        object.__setattr__(self, "target", cleaned)

    def describe(self) -> str:
        if self.kind is WhatIfKind.REMOVE_STEP:
            return f"removing step '{self.target}'"
        return f"dropping the starting fact '{self.target}'"


@dataclass(frozen=True)
class StepBreakage:
    """How one step broke during a What-If test.

    - steps_away: 1 means the change hit this step directly; 2 means it broke because a
      step it depends on broke; and so on.
    - hit_directly: True if the step itself lost a fact it needs, False if it only
      broke because something it relies on broke first.
    """

    step_id: str
    step_title: str
    steps_away: int
    hit_directly: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class BreakageReport:
    """The outcome of a What-If test, in plain English."""

    change: WhatIfChange
    checked_by: CheckKind
    broken_steps: tuple[StepBreakage, ...]
    already_broken_step_ids: tuple[str, ...]
    goal_reached_before: bool
    goal_reached_after: bool
    headline: str
    explanation: str
    caveat: str
