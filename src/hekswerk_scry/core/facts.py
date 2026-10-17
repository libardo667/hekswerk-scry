"""Tidying facts so that stray spaces never make two copies of a fact look different."""


def normalize_fact(text: str) -> str:
    """Return `text` with outer spaces removed and inner runs of whitespace collapsed.

    Facts are compared as text. Tidying spaces means " x + 7 > 0" and "x + 7  > 0"
    count as the same fact. It does not make "x+7>0" match "x + 7 > 0": deciding
    whether two differently written formulas mean the same thing is a job for Lean.
    """
    return " ".join(text.split())
