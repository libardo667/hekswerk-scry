"""An outline: a result, and every theorem and definition in its project that it rests on.

A proof map follows one proof tactic by tactic. That is the level Lean is persuaded at, not
the level a proof is understood at: the ideas usually live in how the theorems of a project
fit together, and in what its definitions say. An outline is that level. Each *part* is one
declaration a person wrote (a theorem, definition, structure, ...), with the parts its
statement mentions and the parts its body uses (a theorem's proof, a definition's value).

Outlines come from Lean's own record of the compiled project (`lean/outline.py`), never
from reading Lean text. The text of each part is kept only to show to people.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

# Kinds whose body is part of what they mean. A theorem's proof is not part of what it
# means: to read a statement you need the definitions it mentions, not the proofs of the
# theorems it mentions.
MEANING_KINDS = frozenset({"definition", "instance", "structure", "class", "inductive type",
                           "opaque definition", "axiom"})


@dataclass(frozen=True)
class UnusedHypothesis:
    """A hypothesis a theorem's statement gives its proof, which the proof never uses."""

    name: str | None  # as written, or None when Lean made the name up
    statement: str


@dataclass(frozen=True)
class OutlinePart:
    part_id: str  # Lean's full name for it, which is unique
    name: str  # the name as written (a private name without the prefix Lean adds)
    kind: str  # "theorem", "definition", "structure", ...
    private: bool
    module: str | None  # None for the file the outline was made from
    file: str | None  # relative to the project
    start_line: int | None
    end_line: int | None
    doc: str | None  # the author's doc string
    statement: str  # Lean's printing of what it states (its type)
    source: str | None  # the lines it is written on
    statement_uses: tuple[str, ...]
    body_uses: tuple[str, ...]
    unused_hypotheses: tuple[UnusedHypothesis, ...] = ()

    @property
    def uses(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.statement_uses + self.body_uses))

    @property
    def lines(self) -> int:
        if self.start_line is None or self.end_line is None:
            return 0
        return self.end_line - self.start_line + 1


class OutlineError(ValueError):
    """An outline that doesn't hang together. The message says what is wrong."""


@dataclass(frozen=True)
class Outline:
    result: str  # the part_id of the theorem outlined
    project: str  # the Lean project's folder
    lean_version: str
    file_sha256: dict[str, str]  # each file a part is written in, as it was
    axioms: tuple[str, ...]  # what Lean reported the result relies on
    parts: dict[str, OutlinePart] = field(default_factory=dict)  # the result first

    def __post_init__(self) -> None:
        if next(iter(self.parts), None) != self.result:
            raise OutlineError(f"An outline's first part must be its result, '{self.result}'.")
        for part_id, part in self.parts.items():
            if part.part_id != part_id:
                raise OutlineError(f"Part '{part_id}' is filed under the wrong name.")
            for used in part.uses:
                if used not in self.parts:
                    raise OutlineError(f"Part '{part_id}' uses '{used}', which isn't in the "
                                       "outline. Make the outline again with `scry lean-outline`.")
            if part.file is not None and part.file not in self.file_sha256:
                raise OutlineError(f"Part '{part_id}' is written in '{part.file}', which has "
                                   "no fingerprint.")

    def used_by(self) -> dict[str, tuple[str, ...]]:
        """For each part, the parts that use it."""
        users: dict[str, list[str]] = {part_id: [] for part_id in self.parts}
        for part_id, part in self.parts.items():
            for used in part.uses:
                users[used].append(part_id)
        return {part_id: tuple(u) for part_id, u in users.items()}

    def claim(self) -> tuple[str, ...]:
        """The parts a person needs to read the result's statement: the parts it mentions,
        and theirs in turn, following a definition's body (what it means) but not a
        theorem's proof. In the order found, nearest first; the result is not included."""
        return tuple(_reach(
            [self.result],
            lambda p: self.parts[p].statement_uses + (
                self.parts[p].body_uses if self.parts[p].kind in MEANING_KINDS else ()),
        )[1:])

    def rests_on(self) -> dict[str, frozenset[str]]:
        """For each part, every other part it rests on, directly or not."""
        return _closures({p: part.uses for p, part in self.parts.items()})


def _reach(start: list[str], next_of: Callable[[str], Iterable[str]]) -> list[str]:
    seen = dict.fromkeys(start)
    queue = list(start)
    while queue:
        for nxt in next_of(queue.pop(0)):
            if nxt not in seen:
                seen[nxt] = None
                queue.append(nxt)
    return list(seen)



def _closures(edges: Mapping[str, Iterable[str]]) -> dict[str, frozenset[str]]:
    """Everything reachable from each node, not counting the node itself.

    Declarations can use each other in a loop (a `mutual` block), so this first groups
    nodes that reach each other (Tarjan's strongly connected components, without
    recursion), then combines the groups' reach in the order Tarjan finishes them, which
    puts every group after the groups it reaches."""
    graph = {n: list(dict.fromkeys(e)) for n, e in edges.items()}
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    group_of: dict[str, int] = {}
    groups: list[list[str]] = []
    for start in graph:
        if start in index:
            continue
        work = [(start, 0)]
        index[start] = low[start] = len(index)
        stack.append(start)
        on_stack.add(start)
        while work:
            node, i = work[-1]
            if i < len(graph[node]):
                work[-1] = (node, i + 1)
                nxt = graph[node][i]
                if nxt not in index:
                    index[nxt] = low[nxt] = len(index)
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, 0))
                elif nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                group: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    group_of[member] = len(groups)
                    group.append(member)
                    if member == node:
                        break
                groups.append(group)
    reach: list[frozenset[str]] = []
    for number, group in enumerate(groups):
        found: set[str] = set(group) if len(group) > 1 else set()
        for member in group:
            for nxt in graph[member]:
                if group_of[nxt] != number:
                    found |= reach[group_of[nxt]] | {nxt}
        reach.append(frozenset(found))
    return {n: reach[group_of[n]] - {n} for n in graph}
