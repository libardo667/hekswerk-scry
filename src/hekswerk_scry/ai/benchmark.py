"""Measuring statement audits: would an audit notice a formal statement that's wrong?

A statement audit that has never missed a planted error hasn't been measured. So, like the
mutation check does for tests, this plants known differences into copies of real
`openai/math` comparator statements (`benchmarks/statement-plants.json`), audits each copy
blind, and scores the result mechanically.

For each challenge there is one unchanged copy (the control) and one copy per plant. All
copies get the same name, sit in folders with meaningless names, and get identical
instructions, so nothing tells the helper which one it is looking at. Its Lean claims are
checked against the copy's own definitions, with the challenge theorems taken out
(they have no proof), so a planted definition shows up in Lean too.

A plant counts as:
- caught: a recorded row with a verdict other than "matches" points at the planted lines;
- a dangerous miss: no such row, but a "matches" row points at them (the audit looked
  and passed it);
- missed: no row points at them at all.

A caught plant whose lines the control audit also flagged is marked: the catch may be
about a real difference that was there before the plant, so a person should check it.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hekswerk_scry.ai.audit import (
    Audit,
    audit_prompt,
    audit_text,
    paper_files_for,
    run_audit,
)
from hekswerk_scry.ai.openrouter import OpenRouterClient
from hekswerk_scry.ai.statement_tools import (
    CHECK_THEOREM,
    MATCHES,
    StatementToolbox,
    VerdictRow,
)
from hekswerk_scry.lean import openai_math
from hekswerk_scry.lean.runner import check_file
from hekswerk_scry.lean.statement import read_statement
from hekswerk_scry.lean.workspace import REPOSITORY, LeanWorkspace, workspace_for_file

PLANTS_FILE = REPOSITORY / "benchmarks" / "statement-plants.json"
PLANTS_FORMAT = "hekswerk-scry/statement-plants"
COPIES_FOLDER = Path(".scry-runs") / "audit-copies"
CONTROL = "control"
# The same for every copy, planted or not: whether the copy is proved is not the question.
COPY_STATUS = ("Whether this formal statement has been proved doesn't matter here: judge only "
               "what it says, against the paper.")
COPY_PROOF_NOTE = "(This file states the result, with `sorry` in place of a proof.)"
COPY_CLAIM_NOTE = (
    "Your code is added to the end of the Lean statement file, after its namespaces close, "
    "so open them (`open OAI.Name in`) or use full names. Every definition in that file is "
    "available; the theorems it states are not, since they have no proof here."
)

DEFAULT_BUDGET_USD = 6.0

CAUGHT = "caught"
DANGEROUS_MISS = "dangerous miss"
MISSED = "missed"


class BenchmarkError(RuntimeError):
    """The benchmark couldn't be set up as described. The message says why."""


@dataclass(frozen=True)
class Plant:
    challenge: str
    plant_id: str
    kind: str
    what: str
    old: str
    new: str


@dataclass(frozen=True)
class Variant:
    """One copy of a challenge's statement: the control, or one with a plant in it."""

    item: openai_math.Challenge
    plant: Plant | None
    statement_file: Path
    planted_lines: tuple[int, int] | None  # in the copy
    original_lines: tuple[int, int] | None  # the same text's lines in the original file

    @property
    def name(self) -> str:
        return self.plant.plant_id if self.plant else CONTROL


# --- the plants ----------------------------------------------------------------------


def load_plants(path: Path = PLANTS_FILE) -> dict[str, list[Plant]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("format") != PLANTS_FORMAT:
        raise BenchmarkError(f"{path} is not a {PLANTS_FORMAT} file.")
    unknown = set(data) - {"format", "version", "about", "challenges"}
    if unknown:
        raise BenchmarkError(f"{path} has fields Scry doesn't know: {', '.join(sorted(unknown))}.")
    plants: dict[str, list[Plant]] = {}
    for challenge, entries in data["challenges"].items():
        seen: set[str] = set()
        for entry in entries:
            fields = {"id", "kind", "what", "old", "new"}
            if set(entry) != fields:
                raise BenchmarkError(f"A plant for {challenge} should have exactly the fields "
                                     f"{', '.join(sorted(fields))}.")
            if entry["id"] in seen or entry["id"] == CONTROL:
                raise BenchmarkError(f"Plant id '{entry['id']}' is used twice in {challenge}.")
            if entry["old"] == entry["new"]:
                raise BenchmarkError(f"Plant '{entry['id']}' in {challenge} changes nothing.")
            seen.add(entry["id"])
            plants.setdefault(challenge, []).append(Plant(
                challenge, str(entry["id"]), str(entry["kind"]), str(entry["what"]),
                str(entry["old"]), str(entry["new"])))
    return plants


def plant_into(original: str, plant: Plant) -> tuple[str, tuple[int, int], tuple[int, int]]:
    """The planted text, the planted lines in it, and the replaced lines in the original."""
    count = original.count(plant.old)
    if count != 1:
        raise BenchmarkError(
            f"Plant '{plant.plant_id}' expects its text exactly once in {plant.challenge}, but "
            f"it occurs {count} times. The statement may have changed upstream; update "
            f"{PLANTS_FILE.name}."
        )
    at = original.index(plant.old)
    first = original.count("\n", 0, at) + 1
    original_lines = (first, first + plant.old.count("\n"))
    planted_lines = (first, first + plant.new.count("\n"))
    return original.replace(plant.old, plant.new), planted_lines, original_lines


def without_theorems(text: str, theorem_names: tuple[str, ...]) -> str:
    """The statement file with its challenge theorems (and their doc comments) taken out.

    Each theorem runs from its `theorem` line to the first line containing `sorry`. Lean
    checks the result (`check_variant`), so a file this gets wrong is refused, not used.
    """
    lines = text.split("\n")
    for full_name in theorem_names:
        short = re.escape(full_name.split(".")[-1])
        header = re.compile(rf"^\s*(theorem|lemma)\s+{short}(\s|$|:)")
        starts = [i for i, line in enumerate(lines) if header.match(line)]
        if len(starts) != 1:
            raise BenchmarkError(f"Expected one declaration of {full_name}, found {len(starts)}.")
        start = starts[0]
        end = next((i for i in range(start, min(len(lines), start + 80))
                    if re.search(r"\bsorry\b", lines[i])), None)
        if end is None:
            raise BenchmarkError(f"{full_name} doesn't end in `sorry`; it isn't a statement.")
        if start > 0 and lines[start - 1].rstrip().endswith("-/"):
            doc = start - 1
            while doc >= 0 and not lines[doc].lstrip().startswith("/--"):
                doc -= 1
            if doc < 0:
                raise BenchmarkError(f"The comment before {full_name} has no start.")
            start = doc
        lines[start:end + 1] = []
    return "\n".join(lines)


# --- the copies ----------------------------------------------------------------------


def copy_folder(workspace: LeanWorkspace, challenge: str, variant: str) -> Path:
    """A folder whose name says nothing about what's in it."""
    digest = hashlib.sha256(f"scry-audit-copy\0{challenge}\0{variant}".encode()).hexdigest()
    return workspace.root / COPIES_FOLDER / digest[:16]


def make_variant(item: openai_math.Challenge, plant: Plant | None) -> Variant:
    workspace = workspace_for_file(item.statement_file)
    original = item.statement_file.read_text(encoding="utf-8")
    if plant is None:
        text, planted, replaced = original, None, None
    else:
        text, planted_span, replaced_span = plant_into(original, plant)
        planted, replaced = planted_span, replaced_span
    folder = copy_folder(workspace, item.name, plant.plant_id if plant else CONTROL)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / item.statement_file.name
    path.write_text(text, encoding="utf-8")
    return Variant(item, plant, path, planted, replaced)


def claim_preamble(variant: Variant) -> str:
    return without_theorems(variant.statement_file.read_text(encoding="utf-8"),
                            variant.item.theorem_names)


def toolbox_for(variant: Variant, paper_files: list[Path]) -> StatementToolbox:
    """Read the copy with Lean and set up the helper's tools for it.

    Fails if Lean rejects the copy, or if the copy without its theorems isn't a clean
    place to check claims (Lean must accept a trivial claim there).
    """
    workspace = workspace_for_file(variant.statement_file)
    reports = {theorem: read_statement(workspace, variant.statement_file, theorem)
               for theorem in variant.item.theorem_names}
    folder = variant.statement_file.parent / "claims"
    folder.mkdir(exist_ok=True)
    trial = folder / "Trial.lean"
    trial.write_text(f"{claim_preamble(variant).rstrip()}\n\ntheorem {CHECK_THEOREM} : True := "
                     "trivial\n", encoding="utf-8")
    check = check_file(workspace, trial, CHECK_THEOREM)
    if not check.passed:
        raise BenchmarkError(f"Claims can't be checked in the {variant.name} copy of "
                             f"{variant.item.name}: {'; '.join(check.problems)}")
    return StatementToolbox(
        workspace=workspace, statement_file=variant.statement_file,
        solution_module=variant.item.solution_module, reports=reports,
        paper_files=paper_files, claim_preamble=claim_preamble(variant),
        claim_note=COPY_CLAIM_NOTE, proof_note=COPY_PROOF_NOTE, claims_folder=folder,
    )


# --- scoring -------------------------------------------------------------------------


def _overlaps(row: VerdictRow, lines: tuple[int, int]) -> bool:
    return row.lean_lines is not None and (
        row.lean_lines[0] <= lines[1] and lines[0] <= row.lean_lines[1])


def score_plant(rows: list[VerdictRow], planted_lines: tuple[int, int]) -> str:
    if any(r.verdict != MATCHES and _overlaps(r, planted_lines) for r in rows):
        return CAUGHT
    if any(r.verdict == MATCHES and _overlaps(r, planted_lines) for r in rows):
        return DANGEROUS_MISS
    return MISSED


def control_flagged(control_rows: list[VerdictRow], original_lines: tuple[int, int]) -> bool:
    """Whether the control audit already flagged the lines the plant replaced."""
    return any(r.verdict != MATCHES and _overlaps(r, original_lines) for r in control_rows)


@dataclass
class VariantResult:
    variant: Variant
    audit: Audit
    score: str | None = None  # None for a control
    also_in_control: bool = False
    catching_rows: list[VerdictRow] = field(default_factory=list)


def score_challenge(results: list[VariantResult]) -> None:
    control = next((r for r in results if r.variant.plant is None), None)
    control_rows = control.audit.toolbox.verdicts if control else []
    for result in results:
        lines = result.variant.planted_lines
        if lines is None:
            continue
        rows = result.audit.toolbox.verdicts
        result.score = score_plant(rows, lines)
        result.catching_rows = [r for r in rows if r.verdict != MATCHES and _overlaps(r, lines)]
        assert result.variant.original_lines is not None
        result.also_in_control = (result.score == CAUGHT and
                                  control_flagged(control_rows, result.variant.original_lines))


# --- running it ----------------------------------------------------------------------


def prepare(names: list[str], plants: dict[str, list[Plant]]) -> list[tuple[Variant, list[Path],
                                                                           tuple[str, ...]]]:
    """Make and Lean-check every copy, before anything is spent on the model."""
    prepared = []
    for name in names:
        if name not in plants:
            raise BenchmarkError(f"There are no plants for '{name}' in {PLANTS_FILE.name}.")
        item = openai_math.challenge(name)
        papers, paper_files = paper_files_for(item)
        if not paper_files:
            raise BenchmarkError(f"{name} has no paper to audit against.")
        for plant in [None, *plants[name]]:
            variant = make_variant(item, plant)
            toolbox_for(variant, paper_files)  # fails here, not after money is spent
            prepared.append((variant, paper_files, papers))
    return prepared


def can_afford(spent: list[float], budget_usd: float) -> bool:
    """Whether another audit fits: what's spent, plus the dearest audit so far, stays within
    the budget. Before the first audit, nothing is known, so it may start."""
    return not spent or sum(spent) + max(spent) <= budget_usd


def run_benchmark(client: OpenRouterClient, names: list[str], out: Path,
                  plants: dict[str, list[Plant]] | None = None,
                  budget_usd: float = DEFAULT_BUDGET_USD) -> Path:
    plants = plants if plants is not None else load_plants()
    prepared = prepare(names, plants)
    out.mkdir(parents=True, exist_ok=True)
    by_challenge: dict[str, list[VariantResult]] = {}
    spent: list[float] = []
    skipped: list[str] = []
    for variant, paper_files, papers in prepared:
        if not can_afford(spent, budget_usd):
            skipped.append(f"{variant.item.name} ({variant.name})")
            continue
        toolbox = toolbox_for(variant, paper_files)
        prompt = audit_prompt(toolbox, variant.item, papers, COPY_STATUS)
        audit = run_audit(client, toolbox, prompt, variant.item.name, papers)
        spent.append(audit.cost_usd)
        (out / f"{variant.item.name}--{variant.name}.md").write_text(
            audit_text(audit), encoding="utf-8")
        by_challenge.setdefault(variant.item.name, []).append(VariantResult(variant, audit))
        _save_rows(out, by_challenge)
    for results in by_challenge.values():
        score_challenge(results)
    summary = out / "summary.md"
    text = render_summary(by_challenge)
    if skipped:
        text += ("\n## Not run (budget of $" + f"{budget_usd:.2f} reached)\n\n"
                 + "\n".join(f"- {name}" for name in skipped) + "\n")
    summary.write_text(text, encoding="utf-8")
    _save_rows(out, by_challenge)
    return summary


def _save_rows(out: Path, by_challenge: dict[str, list[VariantResult]]) -> None:
    data: dict[str, Any] = {
        name: [{
            "variant": r.variant.name,
            "planted_lines": r.variant.planted_lines,
            "score": r.score, "also_in_control": r.also_in_control,
            "cost_usd": round(r.audit.cost_usd, 4),
            "hit_round_limit": r.audit.turn.hit_round_limit,
            "rows": [vars(row) for row in r.audit.toolbox.verdicts],
        } for r in results]
        for name, results in by_challenge.items()
    }
    (out / "results.json").write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                      encoding="utf-8")


def render_summary(by_challenge: dict[str, list[VariantResult]]) -> str:
    plants = [r for results in by_challenge.values() for r in results if r.score is not None]
    counts = {s: sum(r.score == s for r in plants) for s in (CAUGHT, DANGEROUS_MISS, MISSED)}
    cost = sum(r.audit.cost_usd for results in by_challenge.values() for r in results)
    lines = [
        "# Statement audit benchmark", "",
        f"{len(plants)} planted differences in {len(by_challenge)} statements: "
        f"{counts[CAUGHT]} caught, {counts[DANGEROUS_MISS]} dangerous misses (a row said "
        f"\"matches\" over the planted lines), {counts[MISSED]} missed. Total cost "
        f"${cost:.2f}.", "",
        "Scored mechanically from the rows each audit recorded. The audits are the AI "
        "helper's reading; the scores only say whether a row pointed at the planted lines "
        "with a verdict other than \"matches\".", "",
        "| Statement | Plant | What was planted | Result | Row that flagged it |",
        "| --- | --- | --- | --- | --- |",
    ]
    for result in plants:
        assert result.variant.plant is not None
        flagged = "; ".join(f"{r.item} ({r.verdict})" for r in result.catching_rows) or "-"
        note = " (control flagged these lines too: check by hand)" if result.also_in_control else ""
        lines.append(f"| {result.variant.item.name} | {result.variant.plant.plant_id} | "
                     f"{result.variant.plant.what} | {result.score}{note} | {flagged} |")
    lines += ["", "## What the unchanged copies' audits flagged", "",
              "Differences the helper reported in the real statements, to compare with "
              "OpenAI's scope notes (which the helper never saw).", ""]
    for name, results in by_challenge.items():
        control = next((r for r in results if r.variant.plant is None), None)
        if control is None:
            continue
        scope = openai_math.scope_note(control.variant.item)
        lines.append(f"### {name} (scope note {scope.name if scope else 'none'})")
        differences = [r for r in control.audit.toolbox.verdicts if r.verdict != MATCHES]
        lines += [f"- {r.item}: {r.verdict}"
                  + (" (affects the main result)" if r.affects_main_result else "")
                  for r in differences] or ["- nothing flagged"]
        lines.append("")
    return "\n".join(lines)
