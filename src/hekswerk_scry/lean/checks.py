"""Checking a Lean-backed proof map with Lean, step by step.

A step is "Lean-checked" only when Lean accepts the whole theorem (see `runner`). If the
theorem fails, the steps where Lean reported an error are marked "Lean found an error",
and every other step is "Not checked": Lean stops checking a block of tactics at its first
error, and in any case nothing inside an unproven theorem counts as proven.
"""

from dataclasses import dataclass
from pathlib import Path

from hekswerk_scry.core.enums import StepStatus
from hekswerk_scry.lean.runner import LeanCheck, LeanMessage, check_file, file_sha256
from hekswerk_scry.lean.workspace import LeanWorkspace, workspace_for_map
from hekswerk_scry.models.proof_map import LeanSource, ProofMap


class LeanSourceMismatchError(ValueError):
    """The proof map was made from a different version of its Lean file."""


@dataclass(frozen=True)
class LeanStepVerdict:
    step_id: str
    status: StepStatus
    lean_errors: tuple[str, ...] = ()
    note: str | None = None


@dataclass(frozen=True)
class LeanMapReport:
    """Lean's verdict on a whole map, and on each of its steps."""

    check: LeanCheck
    verdicts: dict[str, LeanStepVerdict]
    errors_outside_steps: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.check.passed


def source_path(workspace: LeanWorkspace, proof_map: ProofMap) -> tuple[LeanSource, Path]:
    """The Lean file a map came from, after confirming it hasn't changed since."""
    source = proof_map.lean_source
    if source is None:
        raise ValueError(
            f"Proof map '{proof_map.map_id}' was not made from a Lean file, so Lean can't "
            "check it. Lean checks need a map made with `scry lean-import`."
        )
    expected = Path(source.project).resolve() if source.project else None
    if expected is not None and expected != workspace.root.resolve():
        raise LeanSourceMismatchError(
            f"This map belongs to the Lean project '{expected}', but Lean was asked to run in "
            f"'{workspace.root}'."
        )
    path = workspace.resolve(source.file)
    if not path.is_file():
        raise LeanSourceMismatchError(f"The map's Lean file '{source.file}' no longer exists.")
    if file_sha256(path) != source.file_sha256:
        raise LeanSourceMismatchError(
            f"'{source.file}' has changed since this map was made from it, so the map's steps "
            "may no longer match the file. Import the theorem again."
        )
    return source, path


def workspace_of(proof_map: ProofMap) -> LeanWorkspace:
    """The Lean project a Lean-backed map belongs to."""
    if proof_map.lean_source is None:
        raise ValueError(f"Proof map '{proof_map.map_id}' was not made from a Lean file.")
    return workspace_for_map(proof_map.lean_source.project)


def check_map_with_lean(workspace: LeanWorkspace, proof_map: ProofMap) -> LeanMapReport:
    source, path = source_path(workspace, proof_map)
    check = check_file(workspace, path, source.theorem)
    return verdicts_from_check(proof_map, check)


def verdicts_from_check(proof_map: ProofMap, check: LeanCheck) -> LeanMapReport:
    errors_by_step, outside = locate_errors(proof_map, check.errors())
    verdicts: dict[str, LeanStepVerdict] = {}
    for step_id in proof_map.steps:
        if check.passed:
            verdicts[step_id] = LeanStepVerdict(step_id, StepStatus.LEAN_CHECKED)
        elif step_id in errors_by_step:
            verdicts[step_id] = LeanStepVerdict(
                step_id, StepStatus.LEAN_REJECTED, tuple(errors_by_step[step_id])
            )
        else:
            verdicts[step_id] = LeanStepVerdict(
                step_id,
                StepStatus.NOT_CHECKED,
                note="Not counted as proven: the theorem as a whole did not pass Lean's check.",
            )
    return LeanMapReport(check=check, verdicts=verdicts, errors_outside_steps=tuple(outside))


def locate_errors(
    proof_map: ProofMap, errors: tuple[LeanMessage, ...]
) -> tuple[dict[str, list[str]], list[str]]:
    """Attach each Lean error to the innermost step whose code contains it."""
    by_step: dict[str, list[str]] = {}
    outside: list[str] = []
    for error in errors:
        step_id = innermost_step_at(proof_map, error.line, error.column)
        text = f"Line {error.line}: {first_line(error.text)}"
        if step_id is None:
            outside.append(text)
        else:
            by_step.setdefault(step_id, []).append(text)
    return by_step, outside


def innermost_step_at(proof_map: ProofMap, line: int, column: int) -> str | None:
    best: str | None = None
    best_size: tuple[int, int] | None = None
    for step_id, step in proof_map.steps.items():
        span = step.lean_range
        if span is None or not span.contains(line, column):
            continue
        size = (span.end_line - span.start_line, span.end_column - span.start_column)
        if best_size is None or size < best_size:
            best, best_size = step_id, size
    return best


def first_line(text: str, limit: int = 300) -> str:
    line = text.strip().splitlines()[0] if text.strip() else "(no details)"
    return line if len(line) <= limit else line[: limit - 3] + "..."
