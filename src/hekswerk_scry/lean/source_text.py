"""Positions in Lean source text.

Lean reports lines counting from 1 and columns counting characters (not bytes) from 0.
Python strings count characters too, so offsets here are plain string indexes.
"""

from hekswerk_scry.models.proof_map import LeanRange


def line_starts(text: str) -> list[int]:
    starts = [0]
    for line in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    return starts


def offsets(text: str, span: LeanRange) -> tuple[int, int]:
    """Character offsets of a range within `text` (the end is exclusive)."""
    starts = line_starts(text)
    return (
        starts[span.start_line - 1] + span.start_column,
        starts[span.end_line - 1] + span.end_column,
    )


def position(text: str, offset: int) -> tuple[int, int]:
    """The (line, column) of a character offset."""
    before = text[:offset]
    return before.count("\n") + 1, len(before) - (before.rfind("\n") + 1)
