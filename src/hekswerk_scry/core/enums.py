"""Plain-English labels used across Hekswerk Scry.

Each enum stores a short machine value (used in files and code). Enums that people
see on screen also have a `label` with the exact wording to show.
"""

from enum import StrEnum


class StepStatus(StrEnum):
    """How far a step has been checked, and by what.

    Only the Lean check may ever produce LEAN_CHECKED or LEAN_REJECTED. The built-in
    wiring check can at most produce WIRING_CHECKED, which means "the facts feed
    into each other correctly", not "the math is right".
    """

    LEAN_CHECKED = "lean_checked"
    LEAN_REJECTED = "lean_rejected"
    WIRING_CHECKED = "wiring_checked"
    WIRING_BROKEN = "wiring_broken"
    NOT_CHECKED = "not_checked"

    @property
    def label(self) -> str:
        return _STEP_STATUS_LABELS[self]


_STEP_STATUS_LABELS: dict[StepStatus, str] = {
    StepStatus.LEAN_CHECKED: "Lean-checked",
    StepStatus.LEAN_REJECTED: "Lean found an error",
    StepStatus.WIRING_CHECKED: "Wiring checked (not proven)",
    StepStatus.WIRING_BROKEN: "Wiring broken",
    StepStatus.NOT_CHECKED: "Not checked",
}


class CheckKind(StrEnum):
    """Which checker produced a result.

    LEAN results are only ever created by `hekswerk_scry.lean.runner`, from an actual
    run of the Lean program.
    """

    WIRING = "wiring"
    LEAN = "lean"

    @property
    def label(self) -> str:
        return _CHECK_KIND_LABELS[self]


_CHECK_KIND_LABELS: dict[CheckKind, str] = {
    CheckKind.WIRING: "Built-in wiring check (follows facts between steps; does not read the math)",
    CheckKind.LEAN: "Lean (checks the math itself)",
}


class ProblemKind(StrEnum):
    """Kinds of wiring problems, for a single step or for the map as a whole."""

    UNKNOWN_DEPENDENCY = "unknown_dependency"
    FACT_NOT_PROVIDED = "fact_not_provided"
    FROM_UNLISTED_STEP = "from_unlisted_step"
    DEPENDENCY_BROKEN = "dependency_broken"
    USES_OWN_CONCLUSION = "uses_own_conclusion"
    GOAL_STEP_MISSING = "goal_step_missing"
    GOAL_STEP_PROVES_SOMETHING_ELSE = "goal_step_proves_something_else"
    GOAL_IS_A_STARTING_FACT = "goal_is_a_starting_fact"
    LOOP = "loop"


class CardStatus(StrEnum):
    """The outcome of checking a Simplification card."""

    READY_TO_SWAP = "ready_to_swap"
    REJECTED = "rejected"
    STALE = "stale"

    @property
    def label(self) -> str:
        return _CARD_STATUS_LABELS[self]


_CARD_STATUS_LABELS: dict[CardStatus, str] = {
    CardStatus.READY_TO_SWAP: "Ready to swap",
    CardStatus.REJECTED: "Rejected",
    CardStatus.STALE: "Stale (the steps it replaces have changed; redraft it)",
}


class ViewKind(StrEnum):
    """The three ways of showing a proof step."""

    PLAIN_ENGLISH = "plain_english"
    MATH = "math"
    CODE = "code"


class WhatIfKind(StrEnum):
    """The kinds of change a What-If test can try."""

    REMOVE_STEP = "remove_step"
    DROP_STARTING_FACT = "drop_starting_fact"
