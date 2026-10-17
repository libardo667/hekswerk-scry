"""Turn Scry's results into plain-English text for the terminal."""

import textwrap

from hekswerk_scry.checker.cards import CardCheck
from hekswerk_scry.checker.scanner import MapScan
from hekswerk_scry.checker.wiring import WiringReport
from hekswerk_scry.models.cards import SimplificationCard
from hekswerk_scry.models.proof_map import ProofMap
from hekswerk_scry.models.what_if import BreakageReport

_WIDTH = 92


def _wrap(text: str, first: str = "  ", rest: str | None = None) -> str:
    return textwrap.fill(
        text,
        width=_WIDTH,
        initial_indent=first,
        subsequent_indent=rest if rest is not None else " " * len(first),
        break_on_hyphens=False,
        break_long_words=False,
    )


def _facts(facts: tuple[str, ...]) -> str:
    return ", ".join(f"'{fact}'" for fact in facts) or "(none)"


def render_map_overview(proof_map: ProofMap) -> str:
    lines = [
        f"{proof_map.title}  [{proof_map.map_id}]",
        _wrap(f"Starting facts: {_facts(proof_map.starting_facts)}"),
        _wrap(f"Goal: '{proof_map.goal}' (proved by step '{proof_map.goal_step_id}')"),
        _wrap(f"Steps: {len(proof_map.steps)}"),
    ]
    return "\n".join(lines)


def render_wiring_report(proof_map: ProofMap, report: WiringReport) -> str:
    lines = [f"Wiring check: {proof_map.title}", _wrap(report.summary), ""]
    for problem in report.map_problems:
        lines.append(_wrap(problem.message, "  ! "))
    for step_id, verdict in report.verdicts.items():
        step = proof_map.steps[step_id]
        goal = "  (goal)" if step_id == proof_map.goal_step_id else ""
        lines.append(f"  [{verdict.status.label}] {step_id}: {step.title}{goal}")
        for problem in verdict.problems:
            lines.append(_wrap(problem.message, "      - "))
        for note in verdict.notes:
            lines.append(_wrap(f"Note: {note}", "      "))
    lines.append(_wrap(f"Receipt {report.receipt.receipt_id} ({report.receipt.checked_by.label})"))
    return "\n".join(lines)


def render_scan(scan: MapScan) -> str:
    lines = [_wrap(scan.overview, ""), ""]
    lines.append("Chokepoints:" if scan.chokepoints else "Chokepoints: none")
    for choke in scan.chokepoints:
        lines.append(f"  * {choke.step_id}: {choke.step_title}")
        lines.append(_wrap(choke.explanation, "      "))
    lines.append("Knots:" if scan.knots else "Knots: none")
    for knot in scan.knots:
        lines.append(f"  * {knot.knot_id}: steps {', '.join(knot.step_ids)}")
        lines.append(_wrap(knot.explanation, "      "))
    lines.append("Unused steps:" if scan.unused_steps else "Unused steps: none")
    for unused in scan.unused_steps:
        lines.append(f"  * {unused.step_id}: {unused.step_title}")
        lines.append(_wrap(unused.explanation, "      "))
    return "\n".join(lines)


def render_breakage(report: BreakageReport) -> str:
    lines = [f"What if: {report.change.describe()}?", _wrap(report.headline)]
    for item in report.broken_steps:
        how = "lost a fact it needs" if item.hit_directly else "relies on a step that broke"
        lines.append(
            _wrap(
                f"{item.step_id}: {item.step_title} ({item.steps_away} step(s) away; {how})",
                "    - ",
            )
        )
        for reason in item.reasons:
            lines.append(_wrap(reason, "        "))
    if not report.broken_steps:
        lines.append(_wrap(report.explanation, "    "))
    if report.already_broken_step_ids:
        lines.append(
            _wrap(
                "Already broken before the change (not counted): "
                + ", ".join(report.already_broken_step_ids),
                "    ",
            )
        )
    lines.append(_wrap(f"Note: {report.caveat}", "    "))
    return "\n".join(lines)


def render_card_check(card: SimplificationCard, check: CardCheck) -> str:
    lines = [
        f"Simplification card '{card.card_id}': {card.title}",
        _wrap(f"Why: {card.why}"),
        _wrap(f"Replaces: {', '.join(card.region_step_ids)}"),
        _wrap(f"With: {', '.join(step.step_id for step in card.replacement_steps) or '(nothing)'}"),
    ]
    if check.boundary is not None:
        inputs = _facts(check.boundary.inputs)
        outputs = _facts(check.boundary.outputs)
        lines.append(_wrap(f"Inputs the replaced steps take from outside: {inputs}"))
        lines.append(_wrap(f"Results the rest of the proof takes from them: {outputs}"))
    lines.append(f"  Status: {check.status.label}")
    for problem in check.problems:
        lines.append(_wrap(problem, "    - "))
    if not check.problems:
        lines.append(_wrap(check.receipt.summary))
    lines.append(_wrap(f"Receipt {check.receipt.receipt_id}"))
    return "\n".join(lines)


def render_history(proof_map: ProofMap) -> str:
    if not proof_map.history:
        return "  No swaps yet."
    lines = []
    for number, record in enumerate(proof_map.history, start=1):
        lines.append(
            _wrap(
                f"{number}. Card '{record.card_id}' ({record.card_title}) replaced "
                f"{', '.join(record.removed_step_ids)} with {', '.join(record.added_step_ids)}. "
                f"Receipt {record.receipt_id}.",
                "  ",
                "     ",
            )
        )
    lines.append(
        _wrap(f"Archived steps kept for inspection: {', '.join(proof_map.archived_steps)}")
    )
    return "\n".join(lines)
