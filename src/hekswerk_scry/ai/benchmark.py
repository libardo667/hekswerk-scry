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

A plant is scored from the recorded rows that point at the planted lines:
- caught: a row names a difference (any verdict but "matches" and "unclear"), and none
  says "matches";
- conflicting: one row names a difference and another says "matches" (a person must judge
  which is about the plant);
- dangerous miss: a row says "matches" and none names a difference (the audit looked and
  passed it; an "unclear" row beside it doesn't change that);
- unresolved: the only rows say "unclear" (an honest abstention, but not a catch);
- missed: no row points at them at all.

These only say *where* the audit pointed, not whether it named the planted change. Whether
a catch's row describes the plant is for a person to judge, and the summary says so.

A caught plant whose lines the control audit also flagged is marked: the catch may be
about a real difference that was there before the plant, so a person should check it.

Every audit records its setup: the model and settings, the instructions and tools and the
code behind them, the copy and every Lean input of its reading, and the paper files
(`audit_setup`). A later run reuses an earlier audit only when that setup is identical and
the audit finished (it didn't stop at its round limit), and the summary says which audits
were reused, from when.
"""

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hekswerk_scry.ai.audit import (
    audit_prompt,
    audit_setup,
    audit_text,
    paper_files_for,
    run_audit,
)
from hekswerk_scry.ai.openrouter import AIProviderError, OpenRouterClient
from hekswerk_scry.ai.run_log import LOG_SUFFIX, RunLog
from hekswerk_scry.ai.statement_tools import (
    CHECK_THEOREM,
    MATCHES,
    UNCLEAR,
    VERDICTS,
    StatementToolbox,
    VerdictRow,
)
from hekswerk_scry.core.hashing import fingerprint_data
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
RESULTS_FILE = "results.json"
RESULTS_FORMAT = "hekswerk-scry/benchmark-results"
RESULTS_VERSION = 2

CAUGHT = "caught"
CONFLICTING = "conflicting"
DANGEROUS_MISS = "dangerous miss"
UNRESOLVED = "unresolved"
MISSED = "missed"
SCORES = (CAUGHT, CONFLICTING, DANGEROUS_MISS, UNRESOLVED, MISSED)


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


def names_difference(row: VerdictRow) -> bool:
    return row.verdict not in (MATCHES, UNCLEAR)


def score_plant(rows: list[VerdictRow], planted_lines: tuple[int, int]) -> str:
    over = [r for r in rows if _overlaps(r, planted_lines)]
    difference = any(names_difference(r) for r in over)
    passed = any(r.verdict == MATCHES for r in over)
    if difference:
        return CONFLICTING if passed else CAUGHT
    if passed:
        return DANGEROUS_MISS
    return UNRESOLVED if over else MISSED


def control_flagged(control_rows: list[VerdictRow], original_lines: tuple[int, int]) -> bool:
    """Whether the control audit already named a difference at the lines the plant replaced."""
    return any(names_difference(r) and _overlaps(r, original_lines) for r in control_rows)


@dataclass
class VariantResult:
    """What one audit of one copy found. `reused_from` is when the audit ran, for one an
    earlier run did; None for an audit this run did."""

    variant: Variant
    rows: list[VerdictRow]
    cost_usd: float
    hit_round_limit: bool
    copy_sha256: str
    setup: dict[str, Any]
    ran_at: str
    reused_from: str | None = None
    score: str | None = None  # None for a control
    also_in_control: bool = False
    catching_rows: list[VerdictRow] = field(default_factory=list)
    passing_rows: list[VerdictRow] = field(default_factory=list)

    @property
    def reused(self) -> bool:
        return self.reused_from is not None


def score_challenge(results: list[VariantResult]) -> None:
    control = next((r for r in results if r.variant.plant is None), None)
    control_rows = control.rows if control else []
    for result in results:
        lines = result.variant.planted_lines
        if lines is None:
            continue
        result.score = score_plant(result.rows, lines)
        result.catching_rows = [r for r in result.rows
                                if names_difference(r) and _overlaps(r, lines)]
        result.passing_rows = [r for r in result.rows
                               if r.verdict == MATCHES and _overlaps(r, lines)]
        assert result.variant.original_lines is not None
        result.also_in_control = (result.score in (CAUGHT, CONFLICTING) and
                                  control_flagged(control_rows, result.variant.original_lines))


# --- running it ----------------------------------------------------------------------


def prepare(names: list[str], plants: dict[str, list[Plant]]
            ) -> list[tuple[Variant, StatementToolbox, tuple[str, ...]]]:
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
            # Fails here, not after money is spent.
            prepared.append((variant, toolbox_for(variant, paper_files), papers))
    return prepared


def can_afford(spent: list[float], budget_usd: float) -> bool:
    """Whether another audit fits: what's spent, plus the dearest audit so far, stays within
    the budget. Before the first audit, nothing is known, so it may start."""
    return not spent or sum(spent) + max(spent) <= budget_usd


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class EarlierResult:
    copy_sha256: str
    rows: list[VerdictRow]
    cost_usd: float
    hit_round_limit: bool
    setup: dict[str, Any] | None  # None: saved before Scry recorded each audit's setup
    ran_at: str | None


def read_results(path: Path) -> dict[str, list[dict[str, Any]]]:
    """The audits a results file holds, by challenge. A file from before Scry recorded each
    audit's setup (version 1, a bare mapping) is read with no setup, so nothing in it can
    be reused. Anything else unexpected is refused."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "format" in data:
        if data.get("format") != RESULTS_FORMAT or data.get("version") != RESULTS_VERSION:
            raise BenchmarkError(f"{path} is a {data.get('format')} file, version "
                                 f"{data.get('version')}; this Scry reads {RESULTS_FORMAT} "
                                 f"version {RESULTS_VERSION}.")
        if set(data) != {"format", "version", "challenges"}:
            raise BenchmarkError(f"{path} has fields Scry doesn't know.")
        data = data["challenges"]
    if not isinstance(data, dict):
        raise BenchmarkError(f"{path} isn't a results file.")
    return data


def earlier_results(out: Path) -> dict[tuple[str, str], EarlierResult]:
    """Audits an earlier run saved in `out`, by (challenge, copy). Refuses a results file it
    can't read completely, rather than guessing at what it meant."""
    path = out / RESULTS_FILE
    if not path.is_file():
        return {}
    found: dict[tuple[str, str], EarlierResult] = {}
    try:
        for challenge, entries in read_results(path).items():
            for entry in entries:
                rows = saved_rows(entry["rows"])
                setup = entry.get("setup")
                if setup is not None and not isinstance(setup, dict):
                    raise TypeError("an audit's setup isn't a mapping")
                found[(challenge, str(entry["variant"]))] = EarlierResult(
                    str(entry["copy_sha256"]), rows, float(entry["cost_usd"]),
                    bool(entry["hit_round_limit"]), setup,
                    str(entry["ran_at"]) if entry.get("ran_at") else None)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise BenchmarkError(f"{path} isn't a complete results file ({exc!r}). Move it away "
                             "or choose another --out folder.") from exc
    return found


def saved_rows(raw: list[dict[str, Any]]) -> list[VerdictRow]:
    rows = [VerdictRow(
        item=str(r["item"]), paper_says=str(r["paper_says"]),
        lean_says=str(r["lean_says"]), verdict=str(r["verdict"]),
        affects_main_result=bool(r["affects_main_result"]),
        lean_lines=_saved_lines(r["lean_lines"]),
        evidence=tuple(r["evidence"]),
    ) for r in raw]
    if any(r.verdict not in VERDICTS for r in rows):
        raise TypeError("a row has an unknown verdict")
    return rows


def reusable(before: EarlierResult, setup: dict[str, Any]) -> bool:
    """An earlier audit stands in for a new one only when it was the same experiment (the
    same setup, which includes the exact copy) and it finished. An audit that stopped at its
    round limit is run again."""
    return (before.setup is not None and not before.hit_round_limit
            and fingerprint_data(before.setup) == fingerprint_data(setup))


def _saved_lines(value: Any) -> tuple[int, int] | None:
    if value is None:
        return None
    first, last = value  # exactly two, or this raises
    if not (isinstance(first, int) and isinstance(last, int)):
        raise TypeError(f"lean_lines {value!r} aren't two line numbers")
    return (first, last)


def run_benchmark(client: OpenRouterClient, names: list[str], out: Path,
                  plants: dict[str, list[Plant]] | None = None,
                  budget_usd: float = DEFAULT_BUDGET_USD) -> Path:
    """Audit every copy, reusing any audit an earlier run in `out` saved for a byte-identical
    copy. `budget_usd` limits what this run spends; reused audits cost nothing again."""
    plants = plants if plants is not None else load_plants()
    prepared = prepare(names, plants)
    out.mkdir(parents=True, exist_ok=True)
    earlier = earlier_results(out)
    by_challenge: dict[str, list[VariantResult]] = {}
    spent: list[float] = []
    skipped: list[str] = []
    stopped: str | None = None
    for variant, toolbox, papers in prepared:
        if stopped is not None:
            skipped.append(f"{variant.item.name} ({variant.name})")
            continue
        sha = file_sha256(variant.statement_file)
        prompt = audit_prompt(toolbox, variant.item, papers, COPY_STATUS)
        setup = audit_setup(client, toolbox, prompt)
        before = earlier.get((variant.item.name, variant.name))
        if before is not None and reusable(before, setup):
            assert before.ran_at is not None
            result = VariantResult(variant, before.rows, before.cost_usd,
                                   before.hit_round_limit, sha, setup, before.ran_at,
                                   reused_from=before.ran_at)
        elif not can_afford(spent, budget_usd):
            skipped.append(f"{variant.item.name} ({variant.name})")
            continue
        else:
            ran_at = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
            log = RunLog(out / f"{variant.item.name}--{variant.name}-"
                         f"{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}{LOG_SUFFIX}")
            about = {
                "title": f"Benchmark audit of {variant.item.name} ({variant.name})",
                "copy": variant.name,
                "plant": None if variant.plant is None else {
                    "id": variant.plant.plant_id, "kind": variant.plant.kind,
                    "what": variant.plant.what, "lines": variant.planted_lines},
            }
            try:
                audit = run_audit(client, toolbox, prompt, variant.item.name, papers,
                                  log, about)
            except AIProviderError as exc:
                # Keep everything finished so far, and say where and why it stopped.
                stopped = f"{variant.item.name} ({variant.name}): {exc}"
                skipped.append(f"{variant.item.name} ({variant.name})")
                continue
            spent.append(audit.cost_usd)
            (out / f"{variant.item.name}--{variant.name}.md").write_text(
                audit_text(audit), encoding="utf-8")
            result = VariantResult(variant, list(audit.toolbox.verdicts), audit.cost_usd,
                                   audit.turn.hit_round_limit, sha, setup, ran_at)
        by_challenge.setdefault(variant.item.name, []).append(result)
        save_results(out, by_challenge)
    for results in by_challenge.values():
        score_challenge(results)
    summary = out / "summary.md"
    text = render_summary(by_challenge)
    if skipped:
        why = (f"the AI provider stopped the run at {stopped}" if stopped
               else f"budget of ${budget_usd:.2f} reached")
        text += (f"\n## Not run ({why})\n\n"
                 + "\n".join(f"- {name}" for name in skipped) + "\n")
    summary.write_text(text, encoding="utf-8")
    save_results(out, by_challenge)
    if stopped is not None:
        raise BenchmarkError(f"The AI provider stopped the run at {stopped}. Everything "
                             f"finished is saved in {out}; run again to continue.")
    return summary


def save_results(out: Path, by_challenge: dict[str, list[VariantResult]]) -> None:
    challenges: dict[str, Any] = {
        name: [{
            "variant": r.variant.name,
            "copy_sha256": r.copy_sha256,
            "planted_lines": r.variant.planted_lines,
            "score": r.score, "also_in_control": r.also_in_control,
            "cost_usd": round(r.cost_usd, 4),
            "hit_round_limit": r.hit_round_limit,
            "ran_at": r.ran_at, "reused_from": r.reused_from,
            "setup": r.setup,
            "rows": [vars(row) for row in r.rows],
        } for r in results]
        for name, results in by_challenge.items()
    }
    data = {"format": RESULTS_FORMAT, "version": RESULTS_VERSION, "challenges": challenges}
    (out / RESULTS_FILE).write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                    encoding="utf-8")


SCORE_MEANINGS = {
    CAUGHT: "a row named a difference there, and none said \"matches\"",
    CONFLICTING: "one row named a difference there and another said \"matches\"",
    DANGEROUS_MISS: "a row said \"matches\" there and none named a difference",
    UNRESOLVED: "the only rows there said \"unclear\"",
    MISSED: "no row pointed there",
}


def render_summary(by_challenge: dict[str, list[VariantResult]]) -> str:
    plants = [r for results in by_challenge.values() for r in results if r.score is not None]
    every = [r for results in by_challenge.values() for r in results]
    counts = {s: sum(r.score == s for r in plants) for s in SCORES}
    cost = sum(r.cost_usd for r in every)
    reused = [r for r in every if r.reused]
    unfinished = [r for r in every if r.hit_round_limit]
    lines = [
        "# Statement audit benchmark", "",
        f"{len(plants)} planted differences in {len(by_challenge)} statements: "
        + ", ".join(f"{counts[s]} {s}" for s in SCORES) + f". Total cost ${cost:.2f}.", "",
        "Scored mechanically from the rows each audit recorded, at the planted lines: "
        + "; ".join(f"**{s}**: {m}" for s, m in SCORE_MEANINGS.items()) + ". "
        "A score says where an audit pointed, not whether its row describes the planted "
        "change: that is for a person to judge, row by row. The audits are the AI helper's "
        "reading.", "",
    ]
    if reused:
        lines += [f"{len(reused)} of {len(every)} audits were not run again: an earlier run "
                  "did the same experiment (identical setup), and they are reused from it. "
                  "Reused audits are not new tries.", ""]
    if unfinished:
        lines += [f"{len(unfinished)} audit(s) stopped at the round limit before finishing; "
                  "their rows are what they recorded by then.", ""]
    lines += [
        "| Statement | Plant | What was planted | Result | Rows at the planted lines | Audit |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for result in plants:
        assert result.variant.plant is not None
        flagged = "; ".join(f"{r.item} ({r.verdict})"
                            for r in result.catching_rows + result.passing_rows) or "-"
        note = " (control flagged these lines too: check by hand)" if result.also_in_control else ""
        when = (f"reused, ran {result.reused_from}" if result.reused
                else f"ran {result.ran_at}")
        if result.hit_round_limit:
            when += "; stopped at the round limit"
        lines.append(f"| {result.variant.item.name} | {result.variant.plant.plant_id} | "
                     f"{result.variant.plant.what} | {result.score}{note} | {flagged} | "
                     f"{when} |")
    lines += ["", "## What the unchanged copies' audits flagged", "",
              "Differences the helper reported in the real statements, to compare with "
              "OpenAI's scope notes (which the helper never saw).", ""]
    for name, results in by_challenge.items():
        control = next((r for r in results if r.variant.plant is None), None)
        if control is None:
            continue
        scope = openai_math.scope_note(control.variant.item)
        lines.append(f"### {name} (scope note {scope.name if scope else 'none'})")
        differences = [r for r in control.rows if r.verdict != MATCHES]  # with "unclear"
        lines += [f"- {r.item}: {r.verdict}"
                  + (" (affects the main result)" if r.affects_main_result else "")
                  for r in differences] or ["- nothing flagged"]
        lines.append("")
    return "\n".join(lines)
