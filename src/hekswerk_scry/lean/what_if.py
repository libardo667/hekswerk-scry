"""What-If tests checked by Lean: make a step do nothing and see what Lean says.

The step's code is replaced with `skip`, a tactic that does nothing, and Lean checks the
changed file. This answers "is this step needed?" for real:

- If Lean still accepts the whole proof, the step was not needed.
- If not, Lean's errors are attached to the steps where they occur.

The original file is never touched; the changed copy lives in the workspace's run folder.
"""

from collections import deque
from dataclasses import replace

from hekswerk_scry.core.enums import CheckKind, WhatIfKind
from hekswerk_scry.lean.checks import first_line, innermost_step_at, source_path
from hekswerk_scry.lean.runner import LeanMessage, check_file
from hekswerk_scry.lean.source_text import offsets
from hekswerk_scry.lean.workspace import LeanWorkspace
from hekswerk_scry.models.proof_map import LeanRange, ProofMap
from hekswerk_scry.models.what_if import BreakageReport, StepBreakage, WhatIfChange

REPLACEMENT = "skip"
LEAN_WHAT_IF_CAVEAT = (
    "Lean checked the changed proof, with the step replaced by `skip` (a tactic that does "
    "nothing). Lean stops checking a block of tactics at its first error, so steps after an "
    "error in the same block were not checked in this test."
)


def run_lean_what_if(
    workspace: LeanWorkspace, proof_map: ProofMap, change: WhatIfChange
) -> BreakageReport:
    if change.kind is not WhatIfKind.REMOVE_STEP:
        raise ValueError(
            "Lean What-If tests can only make a step do nothing for now. Dropping a starting "
            "fact means changing the theorem's statement, which Scry doesn't do yet."
        )
    step = proof_map.steps.get(change.target)
    if step is None:
        raise ValueError(f"There is no step '{change.target}' in this map.")
    if step.lean_range is None:
        owner = step.lean_introduced_by or "(unknown)"
        raise ValueError(
            f"Step '{change.target}' has no code of its own: it is the justification for a "
            f"hypothesis introduced by step '{owner}'. Try that step instead."
        )
    source, path = source_path(workspace, proof_map)
    original = path.read_text(encoding="utf-8")
    span = step.lean_range
    start, end = offsets(original, span)
    edited = original[:start] + REPLACEMENT + original[end:]

    before = check_file(workspace, path, source.theorem)
    after = check_file(workspace, path, source.theorem, source_text=edited)

    removed = steps_inside(proof_map, step.lean_range)
    distance = distances_from(proof_map, change.target)
    before_errors = {_error_key(e) for e in before.errors()}
    broken: dict[str, list[str]] = {}
    at_change: list[str] = []
    outside: list[str] = []
    for error in after.errors():
        line, column = original_position(original, edited, start, end, error)
        if _error_key(replace(error, line=line, column=column)) in before_errors:
            continue
        where = innermost_step_at(proof_map, line, column)
        text = f"Line {line}: {first_line(error.text)}"
        if where in removed:
            at_change.append(text)
        elif where is None:
            outside.append(text)
        else:
            broken.setdefault(where, []).append(text)

    breakages = tuple(
        sorted(
            (
                StepBreakage(
                    step_id=step_id,
                    step_title=proof_map.steps[step_id].title,
                    steps_away=distance.get(step_id, 0),
                    hit_directly=True,
                    reasons=tuple(reasons),
                )
                for step_id, reasons in broken.items()
            ),
            key=lambda b: (proof_map.steps[b.step_id].lean_range or span).start_line,
        )
    )
    headline, explanation = _describe(
        change, step.title, after.passed, breakages, at_change, outside
    )
    return BreakageReport(
        change=change,
        checked_by=CheckKind.LEAN,
        broken_steps=breakages,
        already_broken_step_ids=tuple(sorted(_steps_with_errors(proof_map, before.errors()))),
        goal_reached_before=before.passed,
        goal_reached_after=after.passed,
        headline=headline,
        explanation=explanation,
        caveat=LEAN_WHAT_IF_CAVEAT,
    )


def original_position(
    original: str, edited: str, start: int, end: int, message: LeanMessage
) -> tuple[int, int]:
    """Translate a position in the edited text back to the original text."""
    edited_lines = edited.splitlines(keepends=True)
    offset = sum(len(line) for line in edited_lines[: message.line - 1]) + message.column
    if offset < start:
        mapped = offset
    elif offset < start + len(REPLACEMENT):
        mapped = start
    else:
        mapped = offset - len(REPLACEMENT) + (end - start)
    before = original[:mapped]
    line = before.count("\n") + 1
    column = len(before) - (before.rfind("\n") + 1)
    return line, column


def steps_inside(proof_map: ProofMap, span: LeanRange) -> set[str]:
    """Steps whose code lies inside `span`, and the justification steps that go with them."""
    inside = {
        sid
        for sid, step in proof_map.steps.items()
        if step.lean_range is not None and span.encloses(step.lean_range)
    }
    return inside | {
        sid for sid, step in proof_map.steps.items() if step.lean_introduced_by in inside
    }


def distances_from(proof_map: ProofMap, step_id: str) -> dict[str, int]:
    """How many arrows away each step is from `step_id`, in either direction."""
    neighbours: dict[str, set[str]] = {sid: set() for sid in proof_map.steps}
    for sid, step in proof_map.steps.items():
        for dep in step.depends_on:
            if dep in neighbours:
                neighbours[sid].add(dep)
                neighbours[dep].add(sid)
    found = {step_id: 0}
    queue = deque([step_id])
    while queue:
        current = queue.popleft()
        for nxt in neighbours[current]:
            if nxt not in found:
                found[nxt] = found[current] + 1
                queue.append(nxt)
    return found


def _steps_with_errors(proof_map: ProofMap, errors: tuple[LeanMessage, ...]) -> set[str]:
    return {
        sid
        for e in errors
        if (sid := innermost_step_at(proof_map, e.line, e.column)) is not None
    }


def _error_key(message: LeanMessage) -> tuple[int, int, str]:
    return (message.line, message.column, first_line(message.text))


def _describe(
    change: WhatIfChange,
    title: str,
    still_accepted: bool,
    broken: tuple[StepBreakage, ...],
    at_change: list[str],
    outside: list[str],
) -> tuple[str, str]:
    name = f"step '{change.target}' ({title})"
    if still_accepted:
        return (
            f"Not needed: Lean still accepts the whole proof when {name} does nothing.",
            "Lean found no errors, no sorry, and only the standard axioms in the changed proof.",
        )
    lines = (
        [f"'{b.step_title}' ({b.step_id}): " + " ".join(b.reasons) for b in broken]
        + [f"Where the step was: {text}" for text in at_change]
        + [f"Outside every step: {text}" for text in outside]
    )
    if broken:
        headline = (
            f"Lean rejects the changed proof: with {name} doing nothing, Lean reports errors "
            f"at {len(broken)} other step(s), starting with '{broken[0].step_title}' "
            f"({broken[0].step_id})."
        )
    else:
        headline = (
            f"Lean rejects the changed proof: with {name} doing nothing, Lean reports errors."
        )
    return headline, "\n".join(lines) or "Lean did not accept the changed proof."
