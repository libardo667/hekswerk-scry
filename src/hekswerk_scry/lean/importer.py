"""Turning a Lean tactic proof into a Scry proof map.

The Lean side (`lean/ScryExport`) elaborates the file and writes a *trace*: for every
tactic step, the goal it works on, the goals it leaves for later steps, the hypotheses
its piece of the finished proof uses, and the hypotheses it introduces with a
justification (as `have` and `suffices` do). This module turns that trace into steps:

- Each tactic becomes a step that proves the goal it works on, assuming the goals it
  leaves behind and the hypotheses it uses. Goals are numbered ("Goal 3: ...") because
  the same statement can appear many times with different things known.
- Each justified hypothesis gets its own small step, "Why h holds", which proves
  "h : statement" from whatever its justification relies on. Steps that use `h` depend
  on that step. If nothing uses `h`, the scanner will report its justification as unused,
  which is how a proved-then-discarded lemma shows up.
- Hypotheses from the theorem statement become starting facts. Other hypotheses (from
  `intro`, `cases`, and so on) are context, not facts, and create no arrows.
- When Lean passes a hypothesis along unchanged under a new identity (as `rw ... at h`
  does for the hypotheses after `h`), the copy is treated as the original.
"""

import json
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hekswerk_scry.checker.wiring import check_wiring
from hekswerk_scry.lean.runner import file_sha256
from hekswerk_scry.lean.worker import LeanWorkerError, worker_for
from hekswerk_scry.lean.workspace import LeanWorkspace
from hekswerk_scry.models.proof_map import (
    LeanRange,
    LeanSource,
    ProofMap,
    ProofStep,
    StepContract,
    StepViews,
)

TRACE_FORMAT = "hekswerk-scry/lean-trace"
EXPORT_TIMEOUT_SECONDS = 900


class LeanImportError(RuntimeError):
    """The Lean exporter failed or produced something unusable."""


def import_theorem(
    workspace: LeanWorkspace,
    path: Path,
    theorem: str,
    *,
    timeout: float = EXPORT_TIMEOUT_SECONDS,
) -> ProofMap:
    """Run the Lean exporter on `path` and build a proof map for `theorem`."""
    workspace.build_imports(path)
    trace = run_exporter(workspace, path, theorem, timeout=timeout)
    source = LeanSource(
        file=workspace.relative(path), theorem=theorem, file_sha256=file_sha256(path),
        project=None if workspace.is_scry_project else str(workspace.root),
    )
    return trace_to_checked_map(trace, source)


def trace_to_checked_map(trace: Mapping[str, Any], source: LeanSource) -> ProofMap:
    """Build the map and insist that it lines up.

    Everything in a trace comes from a proof Lean finished, so every fact a step needs
    must be provided somewhere. If the map doesn't line up, the exporter or the importer
    lost something Lean recorded. That is a Scry bug, and a map built from it would be
    misleading, so the import fails instead of returning it.
    """
    proof_map = trace_to_proof_map(trace, source)
    report = check_wiring(proof_map)
    if not report.passed:
        first = next(
            (p.message for v in report.verdicts.values() for p in v.problems),
            report.map_problems[0].message if report.map_problems else report.summary,
        )
        raise LeanImportError(
            f"Scry bug: the map made from '{source.theorem}' doesn't line up, so part of "
            f"what Lean recorded was lost on the way. {report.summary} First problem: {first}"
        )
    return proof_map


def run_exporter(
    workspace: LeanWorkspace, path: Path, theorem: str, *, timeout: float
) -> dict[str, Any]:
    if not workspace.exporter.is_file():
        raise LeanImportError(
            f"Scry's exporter for {workspace.toolchain} isn't built (expected "
            f"{workspace.exporter}). Run `make lean-setup`."
        )
    worker = worker_for(workspace)
    if worker is not None:
        try:
            reply = worker.ask("export", path, theorem, timeout=timeout)
        except LeanWorkerError as exc:
            raise LeanImportError(f"The Lean exporter failed: {exc}") from exc
        if reply.timed_out:
            raise LeanImportError(
                f"The Lean exporter took longer than {timeout:.0f} seconds and was stopped."
            )
        return _checked_trace(reply.result)
    command = [str(workspace.lake), "env", str(workspace.exporter), str(path.resolve()), theorem]
    try:
        completed = subprocess.run(
            command,
            cwd=workspace.root,
            env=workspace.environment(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise LeanImportError(
            f"The Lean exporter took longer than {timeout:.0f} seconds and was stopped."
        ) from exc
    if completed.returncode != 0:
        details = (completed.stderr.strip() or completed.stdout.strip())[-2000:]
        raise LeanImportError(f"The Lean exporter failed: {details}")
    last_line = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else ""
    try:
        trace = json.loads(last_line)
    except json.JSONDecodeError as exc:
        raise LeanImportError("The Lean exporter's output was not valid JSON.") from exc
    return _checked_trace(trace)


def _checked_trace(trace: Any) -> dict[str, Any]:
    if not isinstance(trace, dict) or trace.get("format") != TRACE_FORMAT:
        raise LeanImportError("The Lean exporter's output is not a Scry Lean trace.")
    return trace


@dataclass
class _Names:
    """Hands out unique, readable fact texts."""

    goal_numbers: dict[str, int] = field(default_factory=dict)
    hypothesis_facts: dict[str, str] = field(default_factory=dict)
    used_texts: dict[str, int] = field(default_factory=dict)

    def goal(self, goal_id: str, goals: Mapping[str, Any]) -> str:
        if goal_id not in self.goal_numbers:
            self.goal_numbers[goal_id] = len(self.goal_numbers) + 1
        target = goals.get(goal_id, {}).get("target", "(unknown goal)")
        return f"Goal {self.goal_numbers[goal_id]}: {target}"

    def hypothesis(self, hyp_id: str, hyps: Mapping[str, Any]) -> str:
        if hyp_id not in self.hypothesis_facts:
            info = hyps.get(hyp_id, {})
            text = f"{info.get('name', '?')} : {info.get('type', '?')}"
            count = self.used_texts.get(text, 0) + 1
            self.used_texts[text] = count
            self.hypothesis_facts[hyp_id] = text if count == 1 else f"{text} (version {count})"
        return self.hypothesis_facts[hyp_id]


def trace_to_proof_map(trace: Mapping[str, Any], source: LeanSource) -> ProofMap:
    """Build a proof map from an exporter trace."""
    goals: Mapping[str, Any] = trace["goals"]
    hyps: Mapping[str, Any] = trace["hypotheses"]
    raw_steps: list[Mapping[str, Any]] = list(trace["steps"])
    names = _Names()

    starting_ids = {fact["hypothesis"]: fact for fact in trace["starting_facts"]}
    starting_facts = tuple(f"{fact['name']} : {fact['type']}" for fact in trace["starting_facts"])
    for hyp_id, fact in starting_ids.items():
        names.hypothesis_facts[hyp_id] = f"{fact['name']} : {fact['type']}"
    goal_fact = names.goal(trace["root_goal"], goals)

    # Number goals in the order steps work on them, so the numbering reads top to bottom.
    for raw in raw_steps:
        for part in raw["parts"]:
            names.goal(part["goal"], goals)

    # Unchanged copies of a hypothesis stand for the original.
    alias: dict[str, str] = {}
    for raw in raw_steps:
        for intro in raw["introduces"]:
            if intro.get("alias_of"):
                alias[intro["hypothesis"]] = intro["alias_of"]

    def original(hyp_id: str) -> str:
        seen: set[str] = set()
        while hyp_id in alias and hyp_id not in seen:
            seen.add(hyp_id)
            hyp_id = alias[hyp_id]
        return hyp_id

    # Who provides each fact: the step working on a goal, or a hypothesis's "why" step.
    goal_provider: dict[str, str] = {}
    why_provider: dict[str, str] = {}
    for raw in raw_steps:
        number = raw["index"] + 1
        parts = raw["parts"]
        for k, part in enumerate(parts):
            step_id = f"s{number}" if len(parts) == 1 else f"s{number}.{k + 1}"
            goal_provider.setdefault(part["goal"], step_id)
        for k, intro in enumerate(raw["introduces"]):
            if not intro.get("alias_of"):
                why_provider[intro["hypothesis"]] = f"s{number}-why{k + 1}"

    def needs(hole_ids: list[str], use_ids: list[str]) -> tuple[list[str], list[str]]:
        facts: list[str] = []
        providers: list[str] = []
        for hole in hole_ids:
            facts.append(names.goal(hole, goals))
            if hole in goal_provider:
                providers.append(goal_provider[hole])
        for use in dict.fromkeys(original(u) for u in use_ids):
            info = hyps.get(use, {})
            if not info.get("is_prop") or info.get("is_auxiliary"):
                continue
            if use in why_provider:
                facts.append(names.hypothesis(use, hyps))
                providers.append(why_provider[use])
            elif use in starting_ids:
                facts.append(names.hypothesis(use, hyps))
        return facts, providers

    steps: dict[str, ProofStep] = {}
    for raw in raw_steps:
        number = raw["index"] + 1
        code = str(raw["code"])
        lean_range = LeanRange(
            start_line=raw["start"]["line"],
            start_column=raw["start"]["column"],
            end_line=raw["end"]["line"],
            end_column=raw["end"]["column"],
        )
        title = _title(code)
        parts = raw["parts"]
        value_range = _range(raw.get("value_range"))
        introducer = (f"s{number}" if len(parts) == 1 else f"s{number}.1") if parts else None
        for k, part in enumerate(parts):
            step_id = f"s{number}" if len(parts) == 1 else f"s{number}.{k + 1}"
            facts, providers = needs(part["holes"], part["uses"])
            goal_text = goals.get(part["goal"], {}).get("target", "")
            steps[step_id] = ProofStep(
                step_id=step_id,
                title=title if len(parts) == 1 else f"{title} (goal {k + 1} of {len(parts)})",
                contract=StepContract(assumes=tuple(facts), proves=names.goal(part["goal"], goals)),
                views=StepViews(math=f"⊢ {goal_text}", code=code),
                depends_on=tuple(dict.fromkeys(p for p in providers if p != step_id)),
                lean_range=lean_range,
                lean_value_range=value_range if k == 0 else None,
            )
        for k, intro in enumerate(raw["introduces"]):
            if intro.get("alias_of"):
                continue
            step_id = f"s{number}-why{k + 1}"
            hyp = hyps.get(intro["hypothesis"], {})
            facts, providers = needs(intro["value_holes"], intro["uses"])
            proves = names.hypothesis(intro["hypothesis"], hyps)
            steps[step_id] = ProofStep(
                step_id=step_id,
                title=f"Why {hyp.get('name', '?')} holds (from step s{number})",
                contract=StepContract(
                    assumes=tuple(fact for fact in facts if fact != proves), proves=proves
                ),
                views=StepViews(math=str(hyp.get("type", "")), code=code),
                depends_on=tuple(dict.fromkeys(p for p in providers if p != step_id)),
                lean_introduced_by=introducer,
            )

    root = trace["root_goal"]
    if root not in goal_provider:
        raise LeanImportError("No step of the proof works on the theorem's own goal.")
    file_name = Path(source.file).name
    return ProofMap(
        map_id=f"lean-{source.theorem}",
        title=f"{source.theorem} ({file_name})",
        starting_facts=starting_facts,
        goal=goal_fact,
        goal_step_id=goal_provider[root],
        steps=steps,
        lean_source=source,
    )


def _range(raw: Mapping[str, Any] | None) -> LeanRange | None:
    if not raw:
        return None
    return LeanRange(
        start_line=raw["start"]["line"],
        start_column=raw["start"]["column"],
        end_line=raw["end"]["line"],
        end_column=raw["end"]["column"],
    )


def _title(code: str, limit: int = 72) -> str:
    first = " ".join(code.strip().splitlines()[0].split()) if code.strip() else "(empty)"
    more = "..." if len(first) > limit or "\n" in code.strip() else ""
    return (first[:limit] + more) if more else first
