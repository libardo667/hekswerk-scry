"""Turn Scry's results into plain-English text for the terminal."""

import textwrap

from hekswerk_scry.checker.cards import CardCheck
from hekswerk_scry.checker.scanner import MapScan
from hekswerk_scry.checker.wiring import WiringReport
from hekswerk_scry.core.enums import CheckKind, StepStatus
from hekswerk_scry.lean.cards import LeanCardCheck, LeanRegion, LeanSimplificationCard
from hekswerk_scry.lean.checks import LeanMapReport
from hekswerk_scry.lean.source_text import offsets
from hekswerk_scry.models.cards import SimplificationCard
from hekswerk_scry.models.proof_map import LeanRange, ProofMap
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
    if report.checked_by is CheckKind.LEAN:
        lines = [
            f"What if step '{report.change.target}' did nothing?  (checked by Lean)",
            _wrap(report.headline),
        ]
        if not report.goal_reached_after:
            lines.extend(_wrap(line, "    - ") for line in report.explanation.splitlines())
        if report.already_broken_step_ids:
            lines.append(
                _wrap(
                    "Lean already reported errors here before the change: "
                    + ", ".join(report.already_broken_step_ids),
                    "    ",
                )
            )
        lines.append(_wrap(f"Note: {report.caveat}", "    "))
        return "\n".join(lines)
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


def render_lean_report(proof_map: ProofMap, report: LeanMapReport) -> str:
    check = report.check
    lines = [
        f"Lean check: {proof_map.title}",
        _wrap(check.receipt.summary),
        _wrap(f"Lean took {check.seconds:.0f} seconds. Axioms used: "
              + (", ".join(check.axioms) if check.axioms else "(not reported)")),
    ]
    for problem in check.problems[1:]:
        lines.append(_wrap(problem, "  ! "))
    counts: dict[StepStatus, int] = {}
    for verdict in report.verdicts.values():
        counts[verdict.status] = counts.get(verdict.status, 0) + 1
    lines.append(
        _wrap(
            "Steps: " + ", ".join(f"{n} {status.label}" for status, n in counts.items())
        )
    )
    for step_id, verdict in report.verdicts.items():
        if verdict.status is StepStatus.LEAN_REJECTED:
            lines.append(f"  [{verdict.status.label}] {step_id}: {proof_map.steps[step_id].title}")
            for error in verdict.lean_errors:
                lines.append(_wrap(error, "      - "))
    for error in report.errors_outside_steps:
        lines.append(_wrap(f"Outside every step: {error}", "  ! "))
    lines.append(_wrap(f"Receipt {check.receipt.receipt_id} ({check.receipt.checked_by.label})"))
    return "\n".join(lines)


def _code(text: str, span: LeanRange, indent: str = "      | ") -> list[str]:
    start, end = offsets(text, span)
    return [indent + line for line in text[start:end].splitlines()]


def _lines(span: LeanRange) -> str:
    if span.start_line == span.end_line:
        return f"line {span.start_line}"
    return f"lines {span.start_line}-{span.end_line}"


def render_lean_region(proof_map: ProofMap, region: LeanRegion, text: str) -> str:
    """Show what re-proving one fact would replace and remove, before anything is changed."""
    what = (
        "the proof of this lemma (after its `:=`)"
        if region.replaces_lemma_value
        else "the rest of this goal's proof"
    )
    lines = [
        f"Re-proving '{region.fact}' (step {region.fact_step_id})",
        _wrap(
            f"Its proof is made of {len(region.removed_step_ids)} step(s): "
            + ", ".join(region.removed_step_ids)
            + ". Nothing outside them relies on anything inside them except the fact itself."
        ),
        "",
        f"  New tactics would replace {what}, {_lines(region.anchor)}:",
        *_code(text, region.anchor),
    ]
    for span in region.removed_spans:
        lines.append(
            f"  Removed, because its lemma is used only inside this proof, {_lines(span)}:"
        )
        lines.extend(_code(text, span))
    return "\n".join(lines)


def render_lean_card_check(card: LeanSimplificationCard, check: LeanCardCheck) -> str:
    lines = [
        f"Simplification card '{card.card_id}': {card.title}",
        _wrap(f"Why: {card.why}") if card.why else "",
        f"  Re-proves: step {card.fact_step_id}"
        + (f" ('{check.region.fact}')" if check.region else ""),
        "  New tactics:",
        *("      | " + line for line in card.replacement.strip("\n").splitlines()),
        f"  Status: {check.status.label}",
    ]
    for problem in check.problems:
        lines.append(_wrap(problem, "    - "))
    if check.lean is not None:
        lines.append(_wrap(check.lean.receipt.summary))
        if check.status.value == "ready_to_swap":
            lines.append(
                _wrap(
                    f"Size: {len(check.region.removed_step_ids) if check.region else 0} step(s) "
                    f"over {check.lines_replaced} line(s) of code would be replaced by "
                    f"{check.lines_added} line(s). (A count, not a judgement of readability.)"
                )
            )
        lines.append(_wrap(f"Receipt {check.lean.receipt.receipt_id} "
                           f"({check.lean.receipt.checked_by.label})"))
    return "\n".join(line for line in lines if line != "")

