"""Tools for checking whether a formal statement says what a paper claims.

The AI helper uses these to line a Lean statement up against the paper it formalizes.
What Lean can settle, Lean settles: the statement's anatomy and the red-flag probes come
from Lean, and the helper can write small Lean checks of its own (a special case the paper
says the result covers, or a concrete example meeting the hypotheses) that Lean judges
against the real proof. Everything else is the helper's reading of the paper and the
statement, with citations, for a person to judge.

The helper also records each row of its point-by-point comparison with `record_verdict`:
the item, what the paper and Lean say, a verdict from a fixed list, whether it changes what
the formal result establishes, the Lean lines it is about, and the evidence it rests on.
Rows are what statement audits are scored on (`ai/benchmark.py`), so they are checked as
they are recorded: an unknown verdict, a line outside the file, or a citation of evidence
that doesn't exist is refused.

The scope notes OpenAI wrote are deliberately not available here: they are the answer
key for judging how well this works.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hekswerk_scry.ai.tools import Evidence, Outcome, ToolRunner, tool
from hekswerk_scry.core.enums import CheckKind
from hekswerk_scry.lean.runner import check_file
from hekswerk_scry.lean.statement import StatementReport
from hekswerk_scry.lean.workspace import LeanWorkspace

MAX_LINES = 200
DEFINITION_PAGE = 4000  # characters of a definition's body shown at a time
MAX_VERDICT_LINES = 25
CHECK_THEOREM = "scry_check"
NOT_IN_FORMALIZATION = "not in the formalization"
MATCHES = "matches"
UNCLEAR = "unclear"
VERDICTS = (
    MATCHES, "Lean assumes more", "Lean concludes less", "Lean covers a special case",
    "differs", NOT_IN_FORMALIZATION, UNCLEAR,
)
_THEOREM_LINE = re.compile(rf"^\s*theorem\s+{CHECK_THEOREM}\b", re.MULTILINE)


@dataclass(frozen=True)
class VerdictRow:
    """One row of the helper's comparison of paper and formal statement (its reading)."""

    item: str
    paper_says: str
    lean_says: str
    verdict: str
    affects_main_result: bool
    lean_lines: tuple[int, int] | None  # None only for "not in the formalization"
    evidence: tuple[str, ...]


@dataclass
class StatementToolbox(ToolRunner):
    """Everything the helper may look at while auditing one formal statement.

    `claim_preamble` is the Lean text the helper's own claims are checked under. By default
    it imports the module that proves the result, so claims can use its theorems. An audit
    of a copy of a statement uses the copy's own definitions instead (`ai/benchmark.py`).
    """

    workspace: LeanWorkspace
    statement_file: Path
    solution_module: str
    reports: dict[str, StatementReport]
    paper_files: list[Path]
    evidence: list[Evidence] = field(default_factory=list)
    checks_run: int = 0
    claim_preamble: str = ""
    claim_note: str = ""
    proof_note: str = "(This file states the result; its proof is in the solution module.)"
    claims_folder: Path | None = None
    verdicts: list[VerdictRow] = field(default_factory=list)
    paper_labels: dict[str, Path] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.paper_labels = label_paper_files(self.paper_files)
        if not self.claim_preamble:
            self.claim_preamble = f"import {self.solution_module}"
            self.claim_note = (f"The solution module `{self.solution_module}` is imported, so "
                               "you can use its theorems by name.")
        if self.claims_folder is None:
            self.claims_folder = self.workspace.root / ".scry-runs" / "claims"

    def definitions(self) -> list[dict[str, Any]]:
        theorem = {"theorem": {"type": "string", "description": "The theorem's full name."}}
        return [
            tool("read_statement", "What a theorem states, as Lean reads it: hypotheses, "
                 "conclusion, the project's own definitions it relies on, and Lean's probes "
                 "for contradictory or unneeded hypotheses.", theorem, ["theorem"]),
            tool("read_definition", "One of the project's definitions: its statement, body, and "
                 f"source lines. A long body comes {DEFINITION_PAGE} characters at a time; the "
                 "reply says where to start for the rest.",
                 {"name": {"type": "string", "description": "Full or last part of the name."},
                  "start": {"type": "integer", "description": "Character of the body to start "
                            "at (from 0). Leave out to start at the beginning."}},
                 ["name"]),
            tool("read_lean_lines", "Lines of the Lean statement file (numbered from 1).",
                 {"first_line": {"type": "integer"}, "last_line": {"type": "integer"}},
                 ["first_line", "last_line"]),
            tool("list_paper_files", "The paper's LaTeX files, with their line counts.", {}, []),
            tool("search_paper", "Find lines of the paper's LaTeX containing a phrase (case "
                 "ignored). Returns file:line for each match.",
                 {"phrase": {"type": "string"}}, ["phrase"]),
            tool("read_paper", "Lines of one LaTeX file of the paper (numbered from 1).",
                 {"file": {"type": "string", "description": "As listed by list_paper_files."},
                  "first_line": {"type": "integer"}, "last_line": {"type": "integer"}},
                 ["file", "first_line", "last_line"]),
            tool("check_lean_claim", "Ask Lean to check a small claim of your own, for "
                 "example a special case the paper says the result covers, or a concrete "
                 "example satisfying the hypotheses. Write one `theorem "
                 f"{CHECK_THEOREM} : ... := by ...` (you may add helper lemmas above it). "
                 f"{self.claim_note} Lean accepts it only with no errors, no sorry and "
                 "standard axioms.",
                 {"lean_code": {"type": "string"}}, ["lean_code"]),
            tool("record_verdict", "Record one row of your point-by-point comparison, before "
                 "writing your report. One row per item (an assumption, a quantifier, a "
                 "domain, a constant, a definition, the conclusion). Rows are checked: the "
                 "verdict must be one of the listed ones, the Lean lines must be the specific "
                 f"lines the row is about (at most {MAX_VERDICT_LINES}), and the evidence must "
                 "be earlier tool results.",
                 {"item": {"type": "string"},
                  "paper_says": {"type": "string"},
                  "lean_says": {"type": "string"},
                  "verdict": {"type": "string", "enum": list(VERDICTS)},
                  "affects_main_result": {
                      "type": "boolean",
                      "description": "True if this changes what the formal result establishes "
                                     "about the paper's main claim; false for side remarks or "
                                     "things the main claim doesn't need."},
                  "lean_first_line": {"type": "integer", "description": "Omit only for 'not "
                                      "in the formalization'."},
                  "lean_last_line": {"type": "integer"},
                  "evidence": {"type": "array", "items": {"type": "string"},
                               "description": "Evidence ids such as E3."}},
                 ["item", "paper_says", "lean_says", "verdict", "affects_main_result",
                  "evidence"]),
        ]

    def handlers(self) -> dict[str, Callable[[dict[str, Any]], Outcome]]:
        return {
            "read_statement": self._read_statement,
            "read_definition": self._read_definition,
            "read_lean_lines": self._read_lean_lines,
            "list_paper_files": self._list_paper_files,
            "search_paper": self._search_paper,
            "read_paper": self._read_paper,
            "check_lean_claim": self._check_lean_claim,
            "record_verdict": self._record_verdict,
        }

    # --- Lean's reading of the statement -------------------------------------------

    def _read_statement(self, arguments: dict[str, Any]) -> Outcome:
        name = str(arguments["theorem"])
        report = self.reports.get(name)
        if report is None:
            available = ", ".join(self.reports)
            raise ValueError(f"No statement read for '{name}'. Available: {available}.")
        lines = [f"Statement: {report.statement}", "Hypotheses and variables:"]
        lines += [f"- {b.name} : {b.type}  ({'hypothesis' if b.is_prop else b.binder})"
                  for b in report.binders] or ["- (none)"]
        lines += [f"Conclusion: {report.conclusion}",
                  f"Project definitions it relies on ({report.definitions_total}):"]
        lines += [f"- [depth {d.depth}] {d.name} ({d.kind})" for d in report.definitions]
        if not report.definitions_complete:
            lines.append(f"(Lean's report lists only the first {len(report.definitions)}; the "
                         "other definitions exist but can't be read here.)")
        lines += [f"Probe {p.kind}: {p.headline}"
                  + (f" Axioms of that proof: {', '.join(p.axioms) or 'none'}." if p.found else "")
                  for p in report.probes]
        if report.proof_left_open:
            lines.append(self.proof_note)
        return Outcome(f"Lean's reading of the statement of {name.split('.')[-1]}",
                       "\n".join(lines), CheckKind.LEAN, report.receipt.receipt_id)

    def _read_definition(self, arguments: dict[str, Any]) -> Outcome:
        wanted = str(arguments["name"])
        start = int(arguments.get("start") or 0)
        for report in self.reports.values():
            for d in report.definitions:
                if d.name == wanted or d.name.endswith("." + wanted):
                    where = (f"{d.module or self.workspace.relative(self.statement_file)}"
                             + (f", lines {d.start_line}-{d.end_line}" if d.start_line else ""))
                    value = d.value or ""
                    if not 0 <= start < max(len(value), 1):
                        raise ValueError(f"The body of {d.name} has {len(value)} characters.")
                    end = min(len(value), start + DEFINITION_PAGE)
                    body = f"\nBody: {value[start:end]}" if value else ""
                    if value and (start > 0 or end < len(value)):
                        body += (f"\n(Characters {start}-{end} of {len(value)}."
                                 + (f" Ask again with start={end} for the rest.)"
                                    if end < len(value) else ")"))
                    title = f"definition {d.name.split('.')[-1]}" + (
                        f" from character {start}" if start else "")
                    return Outcome(title, f"{d.name} ({d.kind}; {where})\nType: {d.type}{body}",
                                   CheckKind.LEAN, report.receipt.receipt_id)
        raise ValueError(f"'{wanted}' isn't one of the project definitions the statement uses.")

    def _read_lean_lines(self, arguments: dict[str, Any]) -> Outcome:
        lines = self.statement_file.read_text(encoding="utf-8").splitlines()
        first, last = _span(arguments, len(lines))
        text = "\n".join(f"{n:4d} | {lines[n - 1]}" for n in range(first, last + 1))
        return Outcome(f"Lean statement lines {first}-{last}", text)

    # --- the paper ------------------------------------------------------------------

    def _list_paper_files(self, _: dict[str, Any]) -> Outcome:
        rows = [f"{label} ({len(p.read_text(encoding='utf-8').splitlines())} lines)"
                for label, p in self.paper_labels.items()]
        return Outcome("list of paper files", "\n".join(rows))

    def label(self, path: Path) -> str:
        return next(label for label, file in self.paper_labels.items() if file == path)

    def _search_paper(self, arguments: dict[str, Any]) -> Outcome:
        phrase = str(arguments["phrase"]).strip().lower()
        if len(phrase) < 3:
            raise ValueError("Search for at least three characters.")
        hits: list[str] = []
        for label, path in self.paper_labels.items():
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if phrase in line.lower():
                    hits.append(f"{label}:{n}: {line.strip()[:200]}")
        shown = hits[:40]
        more = f"\n(and {len(hits) - 40} more)" if len(hits) > 40 else ""
        return Outcome(f"paper search for '{phrase}'",
                       "\n".join(shown) + more if shown else "No matches.")

    def _read_paper(self, arguments: dict[str, Any]) -> Outcome:
        name = str(arguments["file"])
        path = self.paper_labels.get(name)
        if path is None:
            raise ValueError(f"No paper file '{name}'. Use list_paper_files.")
        lines = path.read_text(encoding="utf-8").splitlines()
        first, last = _span(arguments, len(lines))
        text = "\n".join(f"{n:4d} | {lines[n - 1]}" for n in range(first, last + 1))
        return Outcome(f"paper {name} lines {first}-{last}", text)

    # --- Lean checks of the helper's own claims --------------------------------------

    def _check_lean_claim(self, arguments: dict[str, Any]) -> Outcome:
        code = str(arguments["lean_code"])
        if not _THEOREM_LINE.search(code):
            raise ValueError(f"Write the claim as `theorem {CHECK_THEOREM} : ... := by ...`.")
        self.checks_run += 1
        assert self.claims_folder is not None
        self.claims_folder.mkdir(parents=True, exist_ok=True)
        path = self.claims_folder / f"Claim{self.checks_run}.lean"
        preamble = self.claim_preamble.rstrip()
        offset = len(preamble.splitlines()) + 1  # the preamble, then one blank line
        path.write_text(f"{preamble}\n\n{code.strip()}\n", encoding="utf-8")
        check = check_file(self.workspace, path, CHECK_THEOREM)
        problems = "\n".join(f"- {p}" for p in check.problems)
        verdict = ("Lean accepts the claim." if check.passed
                   else f"Lean does not accept the claim:\n{problems}")
        errors = "".join(
            f"\n  {'line ' + str(e.line - offset) if e.line > offset else 'before your code'}: "
            f"{e.text.strip().splitlines()[0][:200]}"
            for e in check.errors()[:5])
        return Outcome(f"Lean check of claim {self.checks_run}: "
                       f"{'accepted' if check.passed else 'not accepted'}",
                       verdict + errors, CheckKind.LEAN, check.receipt.receipt_id)


    # --- the comparison table ------------------------------------------------------

    def _record_verdict(self, arguments: dict[str, Any]) -> Outcome:
        verdict = str(arguments["verdict"])
        if verdict not in VERDICTS:
            raise ValueError(f"'{verdict}' isn't a verdict. Use one of: {', '.join(VERDICTS)}.")
        if not isinstance(arguments["affects_main_result"], bool):
            raise ValueError("affects_main_result must be true or false.")
        first, last = arguments.get("lean_first_line"), arguments.get("lean_last_line")
        lines: tuple[int, int] | None = None
        if first is None and last is None:
            if verdict != NOT_IN_FORMALIZATION:
                raise ValueError("Give the Lean lines this row is about (lean_first_line and "
                                 f"lean_last_line); only '{NOT_IN_FORMALIZATION}' may omit them.")
        else:
            total = len(self.statement_file.read_text(encoding="utf-8").splitlines())
            if first is None or last is None:
                raise ValueError("Give both lean_first_line and lean_last_line.")
            lines = (int(first), int(last))
            if not 1 <= lines[0] <= lines[1] <= total:
                raise ValueError(f"Lines {lines[0]}-{lines[1]} aren't in the statement file "
                                 f"(it has {total} lines).")
            if lines[1] - lines[0] + 1 > MAX_VERDICT_LINES:
                raise ValueError(f"Point at the specific lines (at most {MAX_VERDICT_LINES}), "
                                 "not a whole region of the file.")
        cited = tuple(dict.fromkeys(str(e).strip().strip("[]") for e in arguments["evidence"]))
        known = {e.evidence_id for e in self.evidence if e.tool != "record_verdict"}
        unknown = [e for e in cited if e not in known]
        if not cited or unknown:
            raise ValueError("Cite at least one earlier tool result; these aren't any: "
                             f"{', '.join(unknown) or '(none given)'}.")
        row = VerdictRow(
            item=str(arguments["item"]), paper_says=str(arguments["paper_says"]),
            lean_says=str(arguments["lean_says"]), verdict=verdict,
            affects_main_result=arguments["affects_main_result"], lean_lines=lines,
            evidence=cited,
        )
        self.verdicts.append(row)
        where = f"lines {lines[0]}-{lines[1]}" if lines else "no Lean lines"
        return Outcome(f"verdict {len(self.verdicts)}: {row.item} ({verdict})",
                       f"Recorded row {len(self.verdicts)}: {row.item}: {verdict} ({where}).")


def label_paper_files(files: list[Path]) -> dict[str, Path]:
    """A name for each paper file that says which file it is: its path inside its paper's
    `build` folder, led by the paper's folder when there is more than one paper (two papers
    can each have a `main.tex`). Names that would still be the same are refused."""
    def inside(path: Path) -> tuple[str, str]:
        for parent in path.parents:
            if parent.name == "build":
                return parent.parent.name, path.relative_to(parent).as_posix()
        return path.parent.name, path.name

    unique = list(dict.fromkeys(files))
    several = len({inside(p)[0] for p in unique}) > 1
    labels: dict[str, Path] = {}
    for path in unique:
        paper, name = inside(path)
        label = f"{paper}/{name}" if several else name
        if label in labels:
            raise ValueError(f"Two paper files would both be called '{label}' ({labels[label]} "
                             f"and {path}); Scry can't tell them apart.")
        labels[label] = path
    return labels


def _span(arguments: dict[str, Any], total: int) -> tuple[int, int]:
    first = max(1, int(arguments["first_line"]))
    last = min(total, int(arguments["last_line"]), first + MAX_LINES - 1)
    if first > last:
        raise ValueError(f"There are only {total} lines.")
    return first, last
