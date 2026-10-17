"""Simplification cards for Lean proofs: prove one fact a different way, and let Lean judge.

A card names one fact of a Lean-backed map (a goal, or a lemma introduced by `have` and
the like) and gives new Lean tactics that prove it. Scry then:

1. Works out the fact's whole proof: the fact's step plus every step whose results are
   used only inside that proof (`regions.proof_of`). It also removes the `have` lines
   whose lemmas are used only inside it, since those lemmas become dead once the proof
   is replaced. Nothing outside the proof relies on anything inside it.
2. Splices the new tactics in where the proof was, and removes the dead lines.
   - For a lemma written `have h : T := value`, the new tactics replace `value`.
   - For a goal, the new tactics replace the rest of that goal's proof.
3. Asks Lean to check the whole changed file. The card is ready only if Lean accepts the
   theorem (no errors, no sorry, only the standard axioms). The theorem's statement sits
   outside every spliced part, and when the swap is applied Scry confirms it is unchanged.

Since Lean checks the whole theorem, a swap can never smuggle in a new assumption: the
theorem's statement is fixed, and the new tactics can only use what is in scope there.
"""

import itertools
import textwrap
from dataclasses import dataclass, replace
from pathlib import Path

from hekswerk_scry.checker.regions import proof_of
from hekswerk_scry.core.enums import CardStatus
from hekswerk_scry.core.hashing import fingerprint_data
from hekswerk_scry.lean.checks import first_line, source_path
from hekswerk_scry.lean.importer import import_theorem
from hekswerk_scry.lean.runner import LeanCheck, check_file
from hekswerk_scry.lean.source_text import offsets, position
from hekswerk_scry.lean.workspace import LeanWorkspace
from hekswerk_scry.models.proof_map import LeanRange, ProofMap, ProofStep, SwapRecord
from hekswerk_scry.models.receipts import Receipt


class LeanRegionError(ValueError):
    """The fact's proof can't be cut out of the file cleanly. The message says why."""


@dataclass(frozen=True)
class LeanSimplificationCard:
    """A proposal to prove one fact of a Lean proof with different tactics.

    The card remembers the file version and the exact contents of every step it would
    remove, taken when it was drafted. If either changes, the card is stale.
    """

    card_id: str
    title: str
    why: str
    fact_step_id: str
    file_sha256: str
    region_fingerprints: tuple[tuple[str, str], ...]
    replacement: str

    def fingerprint(self) -> str:
        return fingerprint_data(
            {
                "card_id": self.card_id,
                "fact_step_id": self.fact_step_id,
                "file_sha256": self.file_sha256,
                "region_fingerprints": [list(pair) for pair in self.region_fingerprints],
                "replacement": self.replacement,
            }
        )


@dataclass(frozen=True)
class LeanRegion:
    """Where a fact's proof sits in the file, and what a swap would replace or remove.

    - anchor: the code the new tactics replace.
    - replaces_lemma_value: True when the anchor is the `value` of `have h : T := value`;
      False when it is the rest of a goal's proof.
    - removed_spans: other code removed entirely (`have` lines that become dead).
    - column: the column the new tactics' lines start at.
    """

    fact_step_id: str
    fact: str
    removed_step_ids: tuple[str, ...]
    anchor: LeanRange
    replaces_lemma_value: bool
    removed_spans: tuple[LeanRange, ...]
    column: int


@dataclass(frozen=True)
class Spliced:
    """The changed file, and where the new tactics ended up in it (lines, from 1)."""

    text: str
    first_line: int
    last_line: int


@dataclass(frozen=True)
class LeanCardCheck:
    card_id: str
    status: CardStatus
    problems: tuple[str, ...]
    region: LeanRegion | None
    spliced: Spliced | None
    lean: LeanCheck | None
    lines_replaced: int
    lines_added: int

    @property
    def receipt(self) -> Receipt | None:
        return self.lean.receipt if self.lean else None


class LeanCardRejectedError(ValueError):
    def __init__(self, check: LeanCardCheck) -> None:
        self.check = check
        super().__init__(
            f"Card '{check.card_id}' can't be applied. {check.status.label}: "
            + " ".join(check.problems)
        )


# --- Finding a fact's proof -------------------------------------------------------------


def find_region(proof_map: ProofMap, text: str, step_id: str) -> LeanRegion:
    """Work out what replacing the proof of `step_id`'s fact would replace and remove."""
    if proof_map.lean_source is None:
        raise LeanRegionError("This map was not made from a Lean file.")
    steps = proof_map.steps
    if step_id not in steps:
        raise LeanRegionError(f"There is no step '{step_id}' in this map.")
    target = steps[step_id]
    fact = target.contract.proves
    group = set(proof_of(proof_map, step_id))
    own_introducer = target.lean_introduced_by

    whys_of: dict[str, list[str]] = {}
    for sid, step in steps.items():
        if step.lean_introduced_by:
            whys_of.setdefault(step.lean_introduced_by, []).append(sid)

    # A `have` line outside the group whose lemma is used only inside it becomes dead.
    removed = set(group)
    for sid in sorted(group):
        introducer = steps[sid].lean_introduced_by
        if introducer is None or introducer in group or introducer == own_introducer:
            continue
        used_elsewhere = [w for w in whys_of[introducer] if w not in group]
        if used_elsewhere:
            other_fact = steps[used_elsewhere[0]].contract.proves
            raise LeanRegionError(
                f"Step '{introducer}' also introduces '{other_fact}', which is used outside "
                f"the proof of '{fact}', so its line can't be removed. Choose a larger fact "
                "whose proof contains both."
            )
        if len(steps[introducer].depends_on) > 1:
            raise LeanRegionError(
                f"Step '{introducer}' does more than introduce a lemma, so its line can't simply "
                f"be removed. Choose a larger fact whose proof contains it."
            )
        removed.add(introducer)

    anchor, replaces_value, column = _anchor(proof_map, step_id, removed)
    _add_dead_code(proof_map, removed, anchor)
    spans = _outermost(
        [span for sid in removed if (span := steps[sid].lean_range) is not None], anchor
    )
    for sid, step in steps.items():
        span = step.lean_range
        if sid in removed or span is None:
            continue
        for cut in (anchor, *spans):
            if _overlap(span, cut) and not span.encloses(cut):
                raise LeanRegionError(
                    f"Step '{sid}' ({step.title}) sits inside the code that would be replaced, "
                    f"but it isn't part of the proof of '{fact}'."
                )
    return LeanRegion(
        fact_step_id=step_id,
        fact=fact,
        removed_step_ids=tuple(sid for sid in proof_map.topological_order() if sid in removed),
        anchor=anchor,
        replaces_lemma_value=replaces_value,
        removed_spans=tuple(spans),
        column=column,
    )


def _add_dead_code(proof_map: ProofMap, removed: set[str], anchor: LeanRange) -> None:
    """Add the steps that go away with the removed code because nothing else needs them.

    A step whose code sits inside the code being cut, and whose results are used nowhere
    or only by removed steps, is dead once the cut is made (for example a hint whose
    result the finished proof never used). So is a "Why h holds" step for a lemma that a
    removed step introduced, if nothing outside the removed steps uses that lemma.
    """
    steps = proof_map.steps
    children = proof_map.children()
    changed = True
    while changed:
        changed = False
        cuts = [anchor, *(span for sid in removed if (span := steps[sid].lean_range))]
        for sid, step in steps.items():
            if sid in removed or not set(children[sid]) <= removed:
                continue
            span = step.lean_range
            inside_cut = span is not None and any(cut.encloses(span) for cut in cuts)
            if inside_cut or (span is None and step.lean_introduced_by in removed):
                removed.add(sid)
                changed = True


def _anchor(
    proof_map: ProofMap, step_id: str, removed: set[str]
) -> tuple[LeanRange, bool, int]:
    steps = proof_map.steps
    target = steps[step_id]
    start_step: ProofStep = target
    if target.lean_introduced_by is not None:
        introducer = steps[target.lean_introduced_by]
        if introducer.lean_value_range is not None and introducer.lean_range is not None:
            return introducer.lean_value_range, True, introducer.lean_range.start_column + 2
        # No `:= value` (as with `suffices h : T`): the lemma is proved by later tactics
        # working on its own goal. Re-prove that goal instead.
        goal_steps = [
            dep for dep in target.depends_on
            if steps[dep].lean_range is not None and steps[dep].lean_introduced_by is None
        ]
        if len(goal_steps) != 1:
            raise LeanRegionError(
                f"'{target.contract.proves}' comes from step '{introducer.step_id}' itself, "
                "with no separate proof to replace (as with a rewrite). Choose a larger fact."
            )
        start_step = steps[goal_steps[0]]
    if start_step.lean_range is None:
        raise LeanRegionError(f"Step '{start_step.step_id}' has no code in the file.")
    begin = start_step.lean_range
    ends = [
        (span.end_line, span.end_column)
        for sid in removed
        if (span := steps[sid].lean_range) is not None
        and (span.start_line, span.start_column) >= (begin.start_line, begin.start_column)
    ]
    end_line, end_column = max(ends)
    anchor = LeanRange(begin.start_line, begin.start_column, end_line, end_column)
    return anchor, False, begin.start_column


def _outermost(spans: list[LeanRange], anchor: LeanRange) -> list[LeanRange]:
    unique = list(dict.fromkeys(spans))
    return sorted(
        (
            span for span in unique
            if not anchor.encloses(span)
            and not any(other != span and other.encloses(span) for other in unique)
        ),
        key=lambda s: (s.start_line, s.start_column),
    )


def _overlap(a: LeanRange, b: LeanRange) -> bool:
    return (a.start_line, a.start_column) < (b.end_line, b.end_column) and (
        b.start_line, b.start_column
    ) < (a.end_line, a.end_column)


# --- Splicing ---------------------------------------------------------------------------


def splice(text: str, region: LeanRegion, replacement: str) -> Spliced:
    """Put `replacement` where the fact's proof was, and remove the dead lines."""
    body = textwrap.dedent(replacement.expandtabs(2)).strip("\n")
    if not body.strip():
        raise LeanRegionError("The replacement is empty.")
    pad = " " * region.column
    lines = body.splitlines()
    if region.replaces_lemma_value:
        new = "by\n" + "\n".join(pad + line if line.strip() else "" for line in lines)
    else:
        new = lines[0] + "".join("\n" + (pad + line if line.strip() else "") for line in lines[1:])

    anchor_start, anchor_end = offsets(text, region.anchor)
    edits = [(anchor_start, anchor_end, new)]
    for span in region.removed_spans:
        start, end = _whole_lines_if_alone(text, *offsets(text, span))
        edits.append((start, end, ""))
    edits.sort()
    for (_, end_a, _), (start_b, _, _) in itertools.pairwise(edits):
        if start_b < end_a:
            raise LeanRegionError("Scry bug: two parts of the swap overlap in the file.")

    result = text
    for start, end, insert in sorted(edits, reverse=True):
        result = result[:start] + insert + result[end:]
    shift = sum(end - start for start, end, insert in edits if end <= anchor_start and not insert)
    first, _ = position(result, anchor_start - shift)
    if region.replaces_lemma_value:
        first += 1
    return Spliced(text=result, first_line=first, last_line=first + len(lines) - 1)


def _whole_lines_if_alone(text: str, start: int, end: int) -> tuple[int, int]:
    """Widen a removal to its whole lines when nothing else is on them.

    A `·` bullet in front counts as nothing else when the bullet holds only this code.
    """
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end == -1 else line_end
    prefix, suffix = text[line_start:start], text[end:line_end]
    if suffix.strip():
        return start, end
    marker = prefix.strip()
    if marker in ("·", "."):
        bullet_column = len(prefix) - len(prefix.lstrip())
        rest = text[line_end + 1 :].splitlines()
        following = next((line for line in rest if line.strip()), "")
        if following and len(following) - len(following.lstrip()) > bullet_column:
            return start, end
    elif marker:
        return start, end
    return line_start, min(line_end + 1, len(text))


# --- Drafting, checking, applying -------------------------------------------------------


def draft_lean_card(
    workspace: LeanWorkspace,
    proof_map: ProofMap,
    fact_step_id: str,
    *,
    card_id: str,
    title: str,
    why: str,
    replacement: str,
) -> LeanSimplificationCard:
    source, path = source_path(workspace, proof_map)
    region = find_region(proof_map, path.read_text(encoding="utf-8"), fact_step_id)
    return LeanSimplificationCard(
        card_id=card_id,
        title=title,
        why=why,
        fact_step_id=fact_step_id,
        file_sha256=source.file_sha256,
        region_fingerprints=tuple(
            (sid, proof_map.steps[sid].fingerprint()) for sid in region.removed_step_ids
        ),
        replacement=replacement,
    )


def check_lean_card(
    workspace: LeanWorkspace, proof_map: ProofMap, card: LeanSimplificationCard
) -> LeanCardCheck:
    """Check `card` against `proof_map` and its Lean file right now. Lean has the last word."""
    source, path = source_path(workspace, proof_map)
    text = path.read_text(encoding="utf-8")
    stale = _stale_problems(proof_map, card, source.file_sha256)
    if stale:
        return _result(card, CardStatus.STALE, stale)
    try:
        region = find_region(proof_map, text, card.fact_step_id)
    except LeanRegionError as exc:
        return _result(card, CardStatus.REJECTED, [str(exc)])
    if set(region.removed_step_ids) != {sid for sid, _ in card.region_fingerprints}:
        return _result(
            card,
            CardStatus.STALE,
            ["The proof of this fact is now made of different steps than when the card was "
             "drafted. Redraft it."],
        )
    try:
        spliced = splice(text, region, card.replacement)
    except LeanRegionError as exc:
        return _result(card, CardStatus.REJECTED, [str(exc)], region)
    lean = check_file(workspace, path, source.theorem, source_text=spliced.text)
    replaced = _lines_in(text, region)
    added = spliced.last_line - spliced.first_line + 1
    if lean.passed:
        return LeanCardCheck(card.card_id, CardStatus.READY_TO_SWAP, (), region, spliced, lean,
                             replaced, added)
    problems = [
        (f"Your replacement, line {error.line - spliced.first_line + 1}: "
         if spliced.first_line <= error.line <= spliced.last_line
         else f"Line {error.line} of the changed file: ") + first_line(error.text)
        for error in lean.errors()
    ] or list(lean.problems)
    return LeanCardCheck(card.card_id, CardStatus.REJECTED, tuple(problems), region, spliced,
                         lean, replaced, added)


def apply_lean_card(
    workspace: LeanWorkspace,
    proof_map: ProofMap,
    card: LeanSimplificationCard,
    out_path: Path,
) -> tuple[ProofMap, Receipt]:
    """Check `card` again and, if Lean accepts it, write the changed proof to `out_path`.

    The original file is never touched. Returns the map of the changed proof (made fresh
    from Lean, with the replaced steps archived and the swap in its history) and the
    receipt of the Lean check that allowed it.
    """
    if out_path.suffix != ".lean":
        raise ValueError(f"'{out_path}' should be a .lean file.")
    if out_path.exists():
        raise ValueError(f"'{out_path}' already exists. Scry won't overwrite it; pick a new name.")
    check = check_lean_card(workspace, proof_map, card)
    if check.status is not CardStatus.READY_TO_SWAP or check.spliced is None or not check.lean:
        raise LeanCardRejectedError(check)
    assert proof_map.lean_source is not None  # source_path checked this
    out_path.write_text(check.spliced.text, encoding="utf-8")
    try:
        new_map = import_theorem(workspace, out_path, proof_map.lean_source.theorem)
        if new_map.goal != proof_map.goal:
            raise ValueError(
                f"Scry bug: the theorem's statement changed during the swap ('{proof_map.goal}' "
                f"became '{new_map.goal}')."
            )
    except Exception:
        out_path.unlink()
        raise

    version = len(proof_map.history) + 1
    removed = check.region.removed_step_ids if check.region else ()
    renamed = {sid: f"v{version}.{sid}" for sid in removed}
    archived = dict(proof_map.archived_steps)
    for sid in removed:
        step = proof_map.steps[sid]
        archived[renamed[sid]] = replace(
            step,
            step_id=renamed[sid],
            depends_on=tuple(renamed.get(dep, dep) for dep in step.depends_on),
        )
    first, last = check.spliced.first_line, check.spliced.last_line
    added_code = {
        sid for sid, step in new_map.steps.items()
        if step.lean_range is not None and first <= step.lean_range.start_line <= last
    }
    added = tuple(
        sid for sid in new_map.topological_order()
        if sid in added_code or new_map.steps[sid].lean_introduced_by in added_code
    )
    record = SwapRecord(
        card_id=card.card_id,
        card_title=card.title,
        removed_step_ids=tuple(renamed[sid] for sid in removed),
        added_step_ids=added,
        receipt_id=check.lean.receipt.receipt_id,
        lean_before=proof_map.lean_source,
        lean_after=new_map.lean_source,
    )
    result = replace(new_map, archived_steps=archived, history=(*proof_map.history, record))
    return result, check.lean.receipt


def _stale_problems(
    proof_map: ProofMap, card: LeanSimplificationCard, file_sha256: str
) -> list[str]:
    if card.file_sha256 != file_sha256:
        return ["The card was drafted against a different version of the Lean file."]
    problems: list[str] = []
    for step_id, fingerprint in card.region_fingerprints:
        current = proof_map.steps.get(step_id)
        if current is None:
            problems.append(f"Step '{step_id}' is no longer in the map.")
        elif current.fingerprint() != fingerprint:
            problems.append(f"Step '{step_id}' has changed since this card was drafted.")
    return problems


def _lines_in(text: str, region: LeanRegion) -> int:
    total = 0
    for span in (region.anchor, *region.removed_spans):
        start, end = offsets(text, span)
        total += text[start:end].count("\n") + 1
    return total


def _result(
    card: LeanSimplificationCard,
    status: CardStatus,
    problems: list[str],
    region: LeanRegion | None = None,
) -> LeanCardCheck:
    return LeanCardCheck(card.card_id, status, tuple(problems), region, None, None, 0, 0)
