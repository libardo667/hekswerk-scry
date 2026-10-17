"""ProofMap, ProofStep, StepContract, and StepViews: the shape of a proof in Scry.

These classes hold content only. They never store whether a step "passed": statuses
are always computed fresh by a checker, so a file can't claim a step was checked.
"""

import heapq
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any, Self

from hekswerk_scry.core.enums import ViewKind
from hekswerk_scry.core.facts import normalize_fact
from hekswerk_scry.core.hashing import fingerprint_data


def _clean_facts(facts: Iterable[str], where: str) -> tuple[str, ...]:
    """Tidy each fact, drop exact repeats, and reject empty facts."""
    cleaned = tuple(dict.fromkeys(normalize_fact(fact) for fact in facts))
    if "" in cleaned:
        raise ValueError(f"{where} contains an empty fact.")
    return cleaned


@dataclass(frozen=True)
class StepContract:
    """What a step needs and what it gives back.

    - assumes: facts that must already be available before this step can be used.
    - proves: the one new fact this step establishes.
    """

    assumes: tuple[str, ...]
    proves: str

    def __post_init__(self) -> None:
        proves = normalize_fact(self.proves)
        if not proves:
            raise ValueError("A step must prove something, but 'proves' is empty.")
        object.__setattr__(self, "assumes", _clean_facts(self.assumes, "'assumes'"))
        object.__setattr__(self, "proves", proves)

    def to_dict(self) -> dict[str, Any]:
        return {"assumes": list(self.assumes), "proves": self.proves}


@dataclass(frozen=True)
class StepViews:
    """Up to three ways of showing the same step. Any of them may be missing."""

    plain_english: str | None = None
    math: str | None = None
    code: str | None = None

    def available_kinds(self) -> tuple[ViewKind, ...]:
        """Return which views this step actually has."""
        present = (
            (ViewKind.PLAIN_ENGLISH, self.plain_english),
            (ViewKind.MATH, self.math),
            (ViewKind.CODE, self.code),
        )
        return tuple(kind for kind, text in present if text and text.strip())

    def to_dict(self) -> dict[str, str | None]:
        return {"plain_english": self.plain_english, "math": self.math, "code": self.code}


@dataclass(frozen=True)
class LeanRange:
    """Where a step's tactic sits in its Lean file.

    Lines count from 1. Columns count characters (not bytes) from 0, as Lean reports them.
    """

    start_line: int
    start_column: int
    end_line: int
    end_column: int

    def __post_init__(self) -> None:
        if self.start_line < 1 or (self.end_line, self.end_column) < (
            self.start_line,
            self.start_column,
        ):
            raise ValueError(f"Not a usable source range: {self.to_dict()}.")

    def contains(self, line: int, column: int) -> bool:
        return (self.start_line, self.start_column) <= (line, column) <= (
            self.end_line,
            self.end_column,
        )

    def encloses(self, other: "LeanRange") -> bool:
        return self.contains(other.start_line, other.start_column) and self.contains(
            other.end_line, other.end_column
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "start_line": self.start_line,
            "start_column": self.start_column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }


@dataclass(frozen=True)
class LeanSource:
    """Which Lean file and theorem a proof map was made from.

    `file` is relative to Scry's Lean workspace. `file_sha256` is the fingerprint of the
    file's exact contents when the map was made, so a map is never checked against a
    different version of the file.
    """

    file: str
    theorem: str
    file_sha256: str

    def to_dict(self) -> dict[str, str]:
        return {"file": self.file, "theorem": self.theorem, "file_sha256": self.file_sha256}


@dataclass(frozen=True)
class ProofStep:
    """One step of a proof.

    `depends_on` lists the steps whose proven facts this step uses. An arrow means
    "uses a fact from", so every fact in `assumes` should come either from one of these
    steps or from the map's starting facts.
    """

    step_id: str
    title: str
    contract: StepContract
    views: StepViews = field(default_factory=StepViews)
    depends_on: tuple[str, ...] = ()
    lean_range: LeanRange | None = None

    def __post_init__(self) -> None:
        if not self.step_id or self.step_id != self.step_id.strip() or " " in self.step_id:
            raise ValueError(
                f"Step ID {self.step_id!r} is not usable: IDs must be non-empty and "
                "contain no spaces."
            )
        object.__setattr__(
            self, "depends_on", tuple(dict.fromkeys(dep.strip() for dep in self.depends_on))
        )

    def fingerprint(self) -> str:
        """Fingerprint everything about this step: contract, views, title, and arrows."""
        return fingerprint_data(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "title": self.title,
            **self.contract.to_dict(),
            "depends_on": list(self.depends_on),
            "views": self.views.to_dict(),
            "lean_range": self.lean_range.to_dict() if self.lean_range else None,
        }


@dataclass(frozen=True)
class SwapRecord:
    """History entry: a Simplification card replaced some steps with others."""

    card_id: str
    card_title: str
    removed_step_ids: tuple[str, ...]
    added_step_ids: tuple[str, ...]
    receipt_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "card_title": self.card_title,
            "removed_step_ids": list(self.removed_step_ids),
            "added_step_ids": list(self.added_step_ids),
            "receipt_id": self.receipt_id,
        }


class DependencyLoopError(ValueError):
    """Raised when steps depend on each other in a circle."""

    def __init__(self, step_ids: tuple[str, ...]) -> None:
        self.step_ids = step_ids
        super().__init__(
            "Some steps depend on each other in a circle, or depend on a step that does: "
            f"{', '.join(step_ids)}. A proof can't use a fact before that fact is proved."
        )


@dataclass(frozen=True)
class ProofMap:
    """A whole proof: starting facts, a goal, and the steps that connect them.

    When a Simplification card replaces some steps, the old steps move into
    `archived_steps` and the swap is recorded in `history`. Nothing is deleted.
    """

    map_id: str
    title: str
    starting_facts: tuple[str, ...]
    goal: str
    goal_step_id: str
    steps: dict[str, ProofStep]
    archived_steps: dict[str, ProofStep] = field(default_factory=dict)
    history: tuple[SwapRecord, ...] = ()
    lean_source: LeanSource | None = None

    def __post_init__(self) -> None:
        goal = normalize_fact(self.goal)
        if not goal:
            raise ValueError("The proof map's goal is empty.")
        for key, step in self.steps.items():
            if key != step.step_id:
                raise ValueError(
                    f"A step is stored under the ID {key!r} but calls itself "
                    f"{step.step_id!r}. The two must match."
                )
        object.__setattr__(
            self, "starting_facts", _clean_facts(self.starting_facts, "'starting_facts'")
        )
        object.__setattr__(self, "goal", goal)
        object.__setattr__(self, "steps", dict(self.steps))
        object.__setattr__(self, "archived_steps", dict(self.archived_steps))

    def fingerprint(self) -> str:
        """Fingerprint the active proof: starting facts, goal, and every active step."""
        return fingerprint_data(
            {
                "map_id": self.map_id,
                "title": self.title,
                "starting_facts": list(self.starting_facts),
                "goal": self.goal,
                "goal_step_id": self.goal_step_id,
                "steps": {sid: step.fingerprint() for sid, step in sorted(self.steps.items())},
                "lean_source": self.lean_source.to_dict() if self.lean_source else None,
            }
        )

    def children(self) -> dict[str, tuple[str, ...]]:
        """Map each step ID to the IDs of the steps that list it as a dependency."""
        children: dict[str, list[str]] = {step_id: [] for step_id in self.steps}
        for step in self.steps.values():
            for dep in step.depends_on:
                if dep in children:
                    children[dep].append(step.step_id)
        return {step_id: tuple(sorted(kids)) for step_id, kids in children.items()}

    def topological_order(self) -> tuple[str, ...]:
        """Return step IDs so that every step comes after the steps it depends on.

        Ties are broken alphabetically, so the order is always the same. Dependencies
        on IDs that don't exist are ignored here; the wiring check reports them.
        Raises DependencyLoopError if steps depend on each other in a circle.
        """
        waiting_on = {step_id: 0 for step_id in self.steps}
        for step in self.steps.values():
            waiting_on[step.step_id] = sum(1 for dep in step.depends_on if dep in self.steps)
        children = self.children()
        ready = [step_id for step_id, count in waiting_on.items() if count == 0]
        heapq.heapify(ready)
        ordered: list[str] = []
        while ready:
            current = heapq.heappop(ready)
            ordered.append(current)
            for child in children[current]:
                waiting_on[child] -= 1
                if waiting_on[child] == 0:
                    heapq.heappush(ready, child)
        if len(ordered) != len(self.steps):
            raise DependencyLoopError(tuple(sorted(set(self.steps) - set(ordered))))
        return tuple(ordered)

    def ancestors_of(self, step_id: str) -> set[str]:
        """Return every step that feeds, directly or indirectly, into `step_id`."""
        found: set[str] = set()
        stack = list(self.steps[step_id].depends_on)
        while stack:
            current = stack.pop()
            if current in self.steps and current not in found:
                found.add(current)
                stack.extend(self.steps[current].depends_on)
        return found

    def descendants_of(self, step_id: str) -> set[str]:
        """Return every step that builds, directly or indirectly, on `step_id`."""
        children = self.children()
        found: set[str] = set()
        stack = list(children.get(step_id, ()))
        while stack:
            current = stack.pop()
            if current not in found:
                found.add(current)
                stack.extend(children[current])
        return found

    def steps_proving(self, fact: str) -> tuple[str, ...]:
        """Return the IDs of every active step that proves `fact`."""
        wanted = normalize_fact(fact)
        return tuple(
            sorted(sid for sid, step in self.steps.items() if step.contract.proves == wanted)
        )

    def with_steps(self, steps: dict[str, ProofStep]) -> Self:
        """Return a copy of this map with a different set of active steps."""
        return replace(self, steps=steps)
