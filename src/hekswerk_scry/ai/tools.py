"""The tools the AI helper may use, all backed by Scry's own checks.

The model has no authority of its own: whatever it wants to know about the proof, it
finds out through these tools, and every answer it gets is recorded as numbered evidence
(E1, E2, ...) labelled with the checker that produced it. Lean results come only from
real Lean runs. The model can draft Simplification cards (Lean judges them) but cannot
apply them; only the person can.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from hekswerk_scry.checker import check_wiring, scan_proof_map
from hekswerk_scry.core.enums import CardStatus, CheckKind, WhatIfKind
from hekswerk_scry.lean.cards import (
    LeanCardCheck,
    LeanRegionError,
    LeanSimplificationCard,
    check_lean_card,
    draft_lean_card,
    find_region,
)
from hekswerk_scry.lean.checks import check_map_with_lean, source_path
from hekswerk_scry.lean.what_if import run_lean_what_if
from hekswerk_scry.lean.workspace import LeanWorkspace
from hekswerk_scry.models import ProofMap, WhatIfChange

MAX_CODE_LINES = 200


@dataclass(frozen=True)
class Evidence:
    """One tool result the AI may cite. `checked_by` is None for plain lookups."""

    evidence_id: str
    tool: str
    arguments: dict[str, Any]
    summary: str
    result: str
    checked_by: CheckKind | None
    receipt_id: str | None = None

    @property
    def label(self) -> str:
        by = self.checked_by.label if self.checked_by else "lookup (no check)"
        return f"{self.evidence_id}: {self.summary} [{by}]"


@dataclass(frozen=True)
class Outcome:
    """What a tool found, before it is numbered as evidence."""

    summary: str
    result: str
    checked_by: CheckKind | None = None
    receipt_id: str | None = None


@dataclass
class DraftedCard:
    card: LeanSimplificationCard
    check: LeanCardCheck
    evidence_id: str


@dataclass
class Toolbox:
    proof_map: ProofMap
    workspace: LeanWorkspace | None
    evidence: list[Evidence] = field(default_factory=list)
    cards: dict[str, DraftedCard] = field(default_factory=dict)

    # --- what the model sees -------------------------------------------------------

    def definitions(self) -> list[dict[str, Any]]:
        def tool(name: str, description: str, properties: dict[str, Any],
                 required: list[str]) -> dict[str, Any]:
            return {"type": "function", "function": {
                "name": name, "description": description,
                "parameters": {"type": "object", "properties": properties,
                               "required": required, "additionalProperties": False}}}

        step = {"step_id": {"type": "string",
                            "description": "A step ID such as 's7' or 's7-why1'."}}
        tools = [
            tool("list_steps", "List every step: its ID, title, and the fact it proves.", {}, []),
            tool("read_step", "Show one step in full: what it assumes, what it proves, its "
                 "code, and which steps it uses and is used by.", step, ["step_id"]),
            tool("scan_map", "Find chokepoints, knots (detours that only produce one result), "
                 "and unused steps. Looks only at which steps feed which.", {}, []),
        ]
        if self.workspace is not None and self.proof_map.lean_source is not None:
            tools += [
                tool("read_lean_code", "Show lines of the Lean file (line numbers from 1).",
                     {"first_line": {"type": "integer"}, "last_line": {"type": "integer"}},
                     ["first_line", "last_line"]),
                tool("check_whole_proof", "Ask Lean whether the theorem is proven as it stands.",
                     {}, []),
                tool("test_step_doing_nothing", "Replace one step with `skip` and ask Lean "
                     "whether the proof still holds. Use this to test whether a step is needed.",
                     step, ["step_id"]),
                tool("show_fact_proof", "Show which steps and which lines of code make up the "
                     "proof of one step's fact, i.e. what a new proof of it would replace.",
                     step, ["step_id"]),
                tool("try_new_proof", "Draft a Simplification card: new Lean tactics that prove "
                     "the fact of `step_id` in place of its current proof. Lean checks the whole "
                     "changed file. Write tactics a person can follow, with `--` comments "
                     "explaining each idea. Returns a card ID; only the person can apply it.",
                     {**step,
                      "tactics": {"type": "string", "description": "The new Lean tactics."},
                      "why": {"type": "string",
                              "description": "Why this proof is clearer, in plain words."}},
                     ["step_id", "tactics", "why"]),
            ]
        return tools

    def run(self, name: str, arguments: dict[str, Any]) -> Evidence:
        """Run one tool and record the result as evidence. Never raises for bad input."""
        handlers: dict[str, Callable[[dict[str, Any]], Outcome]] = {
            "list_steps": self._list_steps,
            "read_step": self._read_step,
            "scan_map": self._scan_map,
            "read_lean_code": self._read_lean_code,
            "check_whole_proof": self._check_whole_proof,
            "test_step_doing_nothing": self._test_step,
            "show_fact_proof": self._show_fact_proof,
            "try_new_proof": self._try_new_proof,
        }
        offered = {t["function"]["name"] for t in self.definitions()}
        handler = handlers.get(name) if name in offered else None
        if handler is None:
            outcome = Outcome(f"unknown tool {name}", f"There is no tool called '{name}'.")
        else:
            try:
                outcome = handler(arguments)
            except (ValueError, KeyError, TypeError) as exc:
                outcome = Outcome(f"{name} failed", f"The tool could not run: {exc}")
        evidence = Evidence(
            evidence_id=f"E{len(self.evidence) + 1}", tool=name, arguments=arguments,
            summary=outcome.summary, result=outcome.result,
            checked_by=outcome.checked_by, receipt_id=outcome.receipt_id,
        )
        self.evidence.append(evidence)
        return evidence

    # --- the tools -------------------------------------------------------------------

    def _step(self, arguments: dict[str, Any]) -> str:
        step_id = str(arguments.get("step_id", ""))
        if step_id not in self.proof_map.steps:
            raise ValueError(f"There is no step '{step_id}' in this map.")
        return step_id

    def _list_steps(self, _: dict[str, Any]) -> Outcome:
        lines = [
            f"{sid}: {step.title} | proves {step.contract.proves}"
            for sid, step in self.proof_map.steps.items()
        ]
        return Outcome(f"list of {len(lines)} steps", "\n".join(lines))

    def _read_step(self, arguments: dict[str, Any]) -> Outcome:
        step_id = self._step(arguments)
        step = self.proof_map.steps[step_id]
        used_by = self.proof_map.children()[step_id]
        span = step.lean_range
        data = {
            "id": step_id, "title": step.title, "assumes": list(step.contract.assumes),
            "proves": step.contract.proves, "uses_steps": list(step.depends_on),
            "used_by_steps": list(used_by), "code": step.views.code,
            "lines": [span.start_line, span.end_line] if span else None,
            "introduced_by": step.lean_introduced_by,
        }
        return Outcome(f"step {step_id}", _json(data))

    def _scan_map(self, _: dict[str, Any]) -> Outcome:
        scan = scan_proof_map(self.proof_map)
        wiring = check_wiring(self.proof_map)
        data = {
            "wiring": wiring.summary,
            "chokepoints": [c.step_id for c in scan.chokepoints],
            "knots": [{"exit": k.exit_step_id, "steps": len(k.step_ids), "output": k.output}
                      for k in scan.knots],
            "unused_steps": [u.step_id for u in scan.unused_steps],
        }
        return Outcome("scan of the map", _json(data), CheckKind.WIRING, wiring.receipt.receipt_id)

    def _lean(self) -> LeanWorkspace:
        if self.workspace is None or self.proof_map.lean_source is None:
            raise ValueError("Lean is not available for this map.")
        return self.workspace

    def _read_lean_code(self, arguments: dict[str, Any]) -> Outcome:
        _, path = source_path(self._lean(), self.proof_map)
        lines = path.read_text(encoding="utf-8").splitlines()
        first = max(1, int(arguments["first_line"]))
        last = min(len(lines), int(arguments["last_line"]), first + MAX_CODE_LINES - 1)
        text = "\n".join(f"{n:4d} | {lines[n - 1]}" for n in range(first, last + 1))
        return Outcome(f"Lean code lines {first}-{last}", text)

    def _check_whole_proof(self, _: dict[str, Any]) -> Outcome:
        report = check_map_with_lean(self._lean(), self.proof_map)
        detail = report.check.receipt.summary + "".join(f"\n- {p}" for p in report.check.problems)
        return Outcome("Lean check of the whole proof", detail, CheckKind.LEAN,
                       report.check.receipt.receipt_id)

    def _test_step(self, arguments: dict[str, Any]) -> Outcome:
        step_id = self._step(arguments)
        report = run_lean_what_if(self._lean(), self.proof_map,
                                  WhatIfChange(WhatIfKind.REMOVE_STEP, step_id))
        return Outcome(f"Lean What-If: step {step_id} doing nothing",
                       f"{report.headline}\n{report.explanation}\nNote: {report.caveat}",
                       CheckKind.LEAN)

    def _show_fact_proof(self, arguments: dict[str, Any]) -> Outcome:
        step_id = self._step(arguments)
        _, path = source_path(self._lean(), self.proof_map)
        try:
            region = find_region(self.proof_map, path.read_text(encoding="utf-8"), step_id)
        except LeanRegionError as exc:
            return Outcome(f"proof of {step_id}'s fact",
                           f"Can't cut this fact's proof out cleanly: {exc}")
        data = {
            "fact": region.fact, "steps": list(region.removed_step_ids),
            "replaces_lines": [region.anchor.start_line, region.anchor.end_line],
            "replaces": ("the lemma's proof after :=" if region.replaces_lemma_value
                         else "the rest of the goal's proof"),
            "also_removes_lines": [[sp.start_line, sp.end_line] for sp in region.removed_spans],
        }
        return Outcome(f"proof of {step_id}'s fact", _json(data))

    def _try_new_proof(self, arguments: dict[str, Any]) -> Outcome:
        step_id = self._step(arguments)
        tactics, why = str(arguments.get("tactics", "")), str(arguments.get("why", ""))
        card_id = f"C{len(self.cards) + 1}"
        workspace = self._lean()
        try:
            card = draft_lean_card(workspace, self.proof_map, step_id, card_id=card_id,
                                   title=f"Re-prove {step_id}", why=why, replacement=tactics)
        except LeanRegionError as exc:
            return Outcome(f"card for {step_id} not drafted", f"Can't re-prove this fact: {exc}")
        check = check_lean_card(workspace, self.proof_map, card)
        self.cards[card_id] = DraftedCard(card, check, f"E{len(self.evidence) + 1}")
        lines = [f"Card {card_id}: {check.status.label}"]
        lines += [f"- {p}" for p in check.problems]
        if check.status is CardStatus.READY_TO_SWAP:
            lines.append(f"Lean accepts it. Size: {check.lines_replaced} line(s) replaced by "
                         f"{check.lines_added}. Only the person can apply it.")
        receipt = check.receipt.receipt_id if check.receipt else None
        by = CheckKind.LEAN if check.lean is not None else None
        return Outcome(f"card {card_id} for {step_id}: {check.status.label}",
                       "\n".join(lines), by, receipt)


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1)
