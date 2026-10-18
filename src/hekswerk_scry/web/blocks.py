"""Blocks the workbench can fold when it draws a Lean-backed proof map.

In a Lean map, `have h : T := by ...` is two steps: the `have` line itself, which carries
the main line of the proof on to the next tactic, and "Why h holds", which proves `h`.
Everything written inside the `have` (the tactics of its `by` block, and `by` blocks nested
in its term) only exists to prove `h`. A *block* is that "why" step together with those
steps. Folded, it is drawn as one box that takes facts in from outside and gives `h` to the
steps that use it. Blocks nest: a `have` inside a block makes a block inside it.

The `have` step itself is never folded into its block. The main line runs from each tactic
to the next, so folding it in would draw arrows in a circle.

Folding any set of blocks at once never draws arrows in a circle either: a block takes in
only facts introduced before it in the source and gives out only its own, so no route can
leave one folded block and come back in through another. A block that broke this (no route
may leave it and re-enter it) would not be offered, rather than drawn wrongly.

This reads only where steps sit in the Lean file and the map's arrows, never their math or
code.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from hekswerk_scry.models.proof_map import LeanRange, ProofMap


@dataclass(frozen=True)
class Block:
    root: str  # the step for the line that writes the block, such as `have h : T := by`
    members: tuple[str, ...]  # in the map's order: the root's "why" steps and all inside
    parent: str | None  # the root of the smallest block around this one
    takes: tuple[str, ...]  # facts its members use that come from outside it
    gives: tuple[str, ...]  # what its root's "why" steps prove


def _span(r: LeanRange) -> tuple[tuple[int, int], tuple[int, int]]:
    return (r.start_line, r.start_column), (r.end_line, r.end_column)


def foldable_blocks(proof_map: ProofMap) -> list[Block]:
    steps = proof_map.steps
    order = proof_map.topological_order()
    position = {step_id: n for n, step_id in enumerate(order)}
    whys: dict[str, list[str]] = {}
    for step_id, step in steps.items():
        if step.lean_introduced_by is not None:
            whys.setdefault(step.lean_introduced_by, []).append(step_id)
    spans = {sid: _span(s.lean_range) for sid, s in steps.items() if s.lean_range is not None}

    def inside(inner: str, outer: str) -> bool:
        (a, b), (c, d) = spans[outer], spans[inner]
        return a <= c and d <= b and (c, d) != (a, b)

    found: dict[str, set[str]] = {}
    for root in spans:
        if root not in whys:
            continue
        written_inside = [s for s in spans if s != root and inside(s, root)]
        if not written_inside:
            continue
        members = set(written_inside) | set(whys[root])
        for step_id in written_inside:
            members |= set(whys.get(step_id, ()))
        if _convex(proof_map, members):
            found[root] = members

    blocks = []
    for root, members in found.items():
        around = [r for r, m in found.items() if r != root and root in m]
        parent = min(around, key=lambda r: len(found[r])) if around else None
        proven = {steps[m].contract.proves for m in members}
        takes = dict.fromkeys(fact for m in sorted(members, key=position.__getitem__)
                              for fact in steps[m].contract.assumes if fact not in proven)
        blocks.append(Block(
            root=root,
            members=tuple(sorted(members, key=position.__getitem__)),
            parent=parent,
            takes=tuple(takes),
            gives=tuple(steps[w].contract.proves for w in whys[root]),
        ))
    blocks.sort(key=lambda b: spans[b.root])  # in source order
    return blocks


def _convex(proof_map: ProofMap, members: set[str]) -> bool:
    """No route leaves `members` and comes back in."""
    children = proof_map.children()
    fed = _closure(members, lambda s: children.get(s, ()))
    feeding = _closure(members, lambda s: proof_map.steps[s].depends_on)
    return not ((fed & feeding) - members)


def _closure(start: set[str], next_of: Callable[[str], Iterable[str]]) -> set[str]:
    seen: set[str] = set()
    todo = list(start)
    while todo:
        for nxt in next_of(todo.pop()):
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return seen
