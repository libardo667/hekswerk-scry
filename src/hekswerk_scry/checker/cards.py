"""Checking and applying Simplification cards.

A card passes only if:
1. None of the steps it replaces have changed since it was drafted (otherwise it is stale).
2. Its replacement steps have fresh IDs and don't depend on the steps being removed.
3. The replacement only assumes facts the original group already took from outside,
   or the map's starting facts, and it proves every fact the rest of the proof takes
   from the group.
4. After the swap, every step that lined up before still lines up, and so do all the
   replacement steps.

`apply_card` re-runs all of this itself at the moment of the swap. It never trusts an
earlier result or a receipt handed to it.
"""

from dataclasses import dataclass, replace

from hekswerk_scry.checker.regions import RegionBoundary, region_boundary
from hekswerk_scry.checker.wiring import check_wiring
from hekswerk_scry.core.enums import CardStatus, CheckKind, ProblemKind, StepStatus
from hekswerk_scry.core.hashing import fingerprint_data
from hekswerk_scry.models.cards import SimplificationCard
from hekswerk_scry.models.proof_map import DependencyLoopError, ProofMap, ProofStep, SwapRecord
from hekswerk_scry.models.receipts import Receipt


@dataclass(frozen=True)
class CardCheck:
    """The result of checking one card against one version of a map.

    `result_map` shows what the map would look like after the swap. It is only set
    when the card is ready to swap.
    """

    card_id: str
    status: CardStatus
    problems: tuple[str, ...]
    boundary: RegionBoundary | None
    result_map: ProofMap | None
    receipt: Receipt


class CardRejectedError(ValueError):
    """Raised by `apply_card` when a card is not ready to swap."""

    def __init__(self, check: CardCheck) -> None:
        self.check = check
        super().__init__(
            f"Card '{check.card_id}' can't be applied. {check.status.label}: "
            + " ".join(check.problems)
        )


def check_card(proof_map: ProofMap, card: SimplificationCard) -> CardCheck:
    """Check whether `card` can safely be applied to `proof_map` right now."""
    stale = _stale_problems(proof_map, card)
    if stale:
        return _result(proof_map, card, CardStatus.STALE, stale)

    shape = _shape_problems(proof_map, card)
    if shape:
        return _result(proof_map, card, CardStatus.REJECTED, shape)

    try:
        boundary = region_boundary(proof_map, card.region_step_ids)
    except DependencyLoopError as exc:
        return _result(proof_map, card, CardStatus.REJECTED, [f"{exc} Fix the loop first."])
    contract = _contract_problems(boundary, card, proof_map.starting_facts)
    if contract:
        return _result(proof_map, card, CardStatus.REJECTED, contract, boundary)

    result_map = _swap(proof_map, card, boundary)
    regressions = _wiring_regressions(proof_map, result_map, card, boundary)
    if regressions:
        return _result(proof_map, card, CardStatus.REJECTED, regressions, boundary)

    return _result(proof_map, card, CardStatus.READY_TO_SWAP, [], boundary, result_map)


def apply_card(proof_map: ProofMap, card: SimplificationCard) -> tuple[ProofMap, Receipt]:
    """Check `card` against `proof_map` again and, if it passes, perform the swap.

    Returns the new map (with the old steps archived and the swap recorded in its
    history) and the receipt of the check that allowed the swap.
    Raises CardRejectedError if the card is stale or rejected.
    """
    check = check_card(proof_map, card)
    if check.status is not CardStatus.READY_TO_SWAP or check.result_map is None:
        raise CardRejectedError(check)
    assert check.boundary is not None  # always set when the card is ready to swap
    record = SwapRecord(
        card_id=card.card_id,
        card_title=card.title,
        removed_step_ids=check.boundary.step_ids,
        added_step_ids=tuple(step.step_id for step in card.replacement_steps),
        receipt_id=check.receipt.receipt_id,
    )
    return replace(check.result_map, history=(*proof_map.history, record)), check.receipt


def _stale_problems(proof_map: ProofMap, card: SimplificationCard) -> list[str]:
    problems: list[str] = []
    for step_id, fingerprint in card.region_fingerprints:
        current = proof_map.steps.get(step_id)
        if current is None:
            problems.append(
                f"Step '{step_id}' has been removed or replaced since this card was drafted."
            )
        elif current.fingerprint() != fingerprint:
            problems.append(f"Step '{step_id}' has changed since this card was drafted.")
    return problems


def _shape_problems(proof_map: ProofMap, card: SimplificationCard) -> list[str]:
    if not card.replacement_steps:
        return ["The card has no replacement steps."]
    problems: list[str] = []
    region = set(card.region_step_ids)
    replacement_ids = [step.step_id for step in card.replacement_steps]
    seen: set[str] = set()
    for step_id in replacement_ids:
        if step_id in seen:
            problems.append(f"Replacement step ID '{step_id}' is used more than once.")
        seen.add(step_id)
        if step_id in region:
            problems.append(
                f"Replacement step ID '{step_id}' is also the ID of a step being replaced. "
                "Give it a new ID so the old and new versions don't get mixed up."
            )
        elif step_id in proof_map.steps:
            problems.append(
                f"Replacement step ID '{step_id}' is already used by another step in the map."
            )
        elif step_id in proof_map.archived_steps:
            problems.append(
                f"Replacement step ID '{step_id}' belonged to a step retired by an earlier "
                "swap. Pick a new ID so the history stays unambiguous."
            )
    for step in card.replacement_steps:
        for dep in step.depends_on:
            if dep in region:
                problems.append(
                    f"Replacement step '{step.step_id}' depends on '{dep}', which this card "
                    "removes."
                )
            elif dep not in seen and dep not in proof_map.steps:
                problems.append(
                    f"Replacement step '{step.step_id}' depends on '{dep}', which is not in "
                    "the map."
                )
    return problems


def _contract_problems(
    boundary: RegionBoundary, card: SimplificationCard, starting_facts: tuple[str, ...]
) -> list[str]:
    problems: list[str] = []
    proved = {step.contract.proves for step in card.replacement_steps}
    for fact in boundary.outputs:
        if fact not in proved:
            problems.append(
                f"The rest of the proof needs '{fact}' from these steps, but the replacement "
                "never proves it."
            )
    # Starting facts are always allowed: using one doesn't change what the theorem assumes.
    allowed = set(boundary.inputs) | set(starting_facts)
    for step in card.replacement_steps:
        for fact in step.contract.assumes:
            if fact not in proved and fact not in allowed:
                problems.append(
                    f"Replacement step '{step.step_id}' assumes '{fact}', which is neither a "
                    "starting fact nor something the original steps used. A swap may not "
                    "bring in new assumptions."
                )
    return problems


def _swap(proof_map: ProofMap, card: SimplificationCard, boundary: RegionBoundary) -> ProofMap:
    """Build the map that results from the swap. Assumes the card passed its checks."""
    region = set(boundary.step_ids)
    provider: dict[str, str] = {}
    for step in card.replacement_steps:
        provider.setdefault(step.contract.proves, step.step_id)

    new_steps: dict[str, ProofStep] = {}
    for step_id, step in proof_map.steps.items():
        if step_id in region:
            continue
        rewired: list[str] = []
        for dep in step.depends_on:
            if dep not in region:
                rewired.append(dep)
                continue
            # Point at the replacement step that now proves the same fact. An arrow to a
            # removed step whose fact was never used is dropped.
            fact = proof_map.steps[dep].contract.proves
            new_dep = provider.get(fact)
            if new_dep is not None and fact in step.contract.assumes:
                rewired.append(new_dep)
        new_steps[step_id] = replace(step, depends_on=tuple(rewired))
    for step in card.replacement_steps:
        new_steps[step.step_id] = step

    archived = dict(proof_map.archived_steps)
    for step_id in boundary.step_ids:
        archived[step_id] = proof_map.steps[step_id]
    goal_step_id = proof_map.goal_step_id
    if goal_step_id in region:
        goal_step_id = provider.get(proof_map.goal, goal_step_id)
    return replace(
        proof_map, steps=new_steps, archived_steps=archived, goal_step_id=goal_step_id
    )


def _wiring_regressions(
    before_map: ProofMap,
    after_map: ProofMap,
    card: SimplificationCard,
    boundary: RegionBoundary,
) -> list[str]:
    before = check_wiring(before_map)
    after = check_wiring(after_map)
    problems: list[str] = []
    for step in card.replacement_steps:
        verdict = after.verdicts[step.step_id]
        if verdict.status is not StepStatus.WIRING_CHECKED:
            details = " ".join(p.message for p in verdict.problems) or " ".join(verdict.notes)
            problems.append(f"Replacement step '{step.step_id}' doesn't line up: {details}")
    region = set(boundary.step_ids)
    for step_id, verdict in before.verdicts.items():
        if step_id in region or verdict.status is not StepStatus.WIRING_CHECKED:
            continue
        now = after.verdicts[step_id]
        if now.status is not StepStatus.WIRING_CHECKED:
            details = " ".join(p.message for p in now.problems)
            problems.append(f"After the swap, step '{step_id}' no longer lines up: {details}")
    if any(p.kind is ProblemKind.LOOP for p in after.map_problems):
        problems.append("The swap would create a loop between steps.")
    if before.goal_reached and not after.goal_reached:
        problems.append("After the swap, the goal would no longer be reached.")
    return problems


def _result(
    proof_map: ProofMap,
    card: SimplificationCard,
    status: CardStatus,
    problems: list[str],
    boundary: RegionBoundary | None = None,
    result_map: ProofMap | None = None,
) -> CardCheck:
    if status is CardStatus.READY_TO_SWAP and boundary is not None:
        inputs = ", ".join(f"'{f}'" for f in boundary.inputs) or "no outside facts"
        outputs = ", ".join(f"'{f}'" for f in boundary.outputs) or "nothing"
        summary = (
            f"Ready to swap: {len(boundary.step_ids)} step(s) can be replaced by "
            f"{len(card.replacement_steps)} step(s). The replacement uses only {inputs} and "
            f"still provides {outputs}, and the rest of the proof still lines up. Wiring "
            "checked (not proven): the replacement's math has not been checked."
        )
    else:
        summary = f"{status.label}: " + " ".join(problems)
    receipt = Receipt.create(
        checked_by=CheckKind.WIRING,
        subject=f"simplification card '{card.card_id}'",
        subject_fingerprint=fingerprint_data(
            {"card": card.fingerprint(), "map": proof_map.fingerprint()}
        ),
        passed=status is CardStatus.READY_TO_SWAP,
        summary=summary,
    )
    return CardCheck(
        card_id=card.card_id,
        status=status,
        problems=tuple(problems),
        boundary=boundary,
        result_map=result_map,
        receipt=receipt,
    )
