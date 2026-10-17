"""Tools for checking whether a formal statement says what a paper claims.

The AI helper uses these to line a Lean statement up against the paper it formalizes.
What Lean can settle, Lean settles: the statement's anatomy and the red-flag probes come
from Lean, and the helper can write small Lean checks of its own (a special case the paper
says the result covers, or a concrete example meeting the hypotheses) that Lean judges
against the real proof. Everything else is the helper's reading of the paper and the
statement, with citations, for a person to judge.

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
CHECK_THEOREM = "scry_check"
_THEOREM_LINE = re.compile(rf"^\s*theorem\s+{CHECK_THEOREM}\b", re.MULTILINE)


@dataclass
class StatementToolbox(ToolRunner):
    """Everything the helper may look at while auditing one formal statement."""

    workspace: LeanWorkspace
    statement_file: Path
    solution_module: str
    reports: dict[str, StatementReport]
    paper_files: list[Path]
    evidence: list[Evidence] = field(default_factory=list)
    checks_run: int = 0

    def definitions(self) -> list[dict[str, Any]]:
        theorem = {"theorem": {"type": "string", "description": "The theorem's full name."}}
        return [
            tool("read_statement", "What a theorem states, as Lean reads it: hypotheses, "
                 "conclusion, the project's own definitions it relies on, and Lean's probes "
                 "for contradictory or unneeded hypotheses.", theorem, ["theorem"]),
            tool("read_definition", "One of the project's definitions in full: its statement, "
                 "body, and source lines.",
                 {"name": {"type": "string", "description": "Full or last part of the name."}},
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
            tool("check_lean_claim", "Ask Lean to check a small claim of your own against the "
                 "real proof, for example a special case the paper says the result covers, or a "
                 f"concrete example satisfying the hypotheses. Write one `theorem {CHECK_THEOREM}"
                 " : ... := by ...` (you may add helper lemmas above it). The proved result is "
                 f"imported from `{self.solution_module}`, so you can use its theorems by name. "
                 "Lean accepts it only with no errors, no sorry and standard axioms.",
                 {"lean_code": {"type": "string"}}, ["lean_code"]),
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
                  f"Project definitions it relies on ({len(report.definitions)}):"]
        lines += [f"- [depth {d.depth}] {d.name} ({d.kind})" for d in report.definitions]
        lines += [f"Probe {p.kind}: {p.headline}" for p in report.probes]
        if report.proof_left_open:
            lines.append("(This file states the result; its proof is in the solution module.)")
        return Outcome(f"Lean's reading of the statement of {name.split('.')[-1]}",
                       "\n".join(lines), CheckKind.LEAN, report.receipt.receipt_id)

    def _read_definition(self, arguments: dict[str, Any]) -> Outcome:
        wanted = str(arguments["name"])
        for report in self.reports.values():
            for d in report.definitions:
                if d.name == wanted or d.name.endswith("." + wanted):
                    where = (f"{d.module or self.workspace.relative(self.statement_file)}"
                             + (f", lines {d.start_line}-{d.end_line}" if d.start_line else ""))
                    body = f"\nBody: {d.value}" if d.value else ""
                    return Outcome(f"definition {d.name.split('.')[-1]}",
                                   f"{d.name} ({d.kind}; {where})\nType: {d.type}{body}",
                                   CheckKind.LEAN, report.receipt.receipt_id)
        raise ValueError(f"'{wanted}' isn't one of the project definitions the statement uses.")

    def _read_lean_lines(self, arguments: dict[str, Any]) -> Outcome:
        lines = self.statement_file.read_text(encoding="utf-8").splitlines()
        first, last = _span(arguments, len(lines))
        text = "\n".join(f"{n:4d} | {lines[n - 1]}" for n in range(first, last + 1))
        return Outcome(f"Lean statement lines {first}-{last}", text)

    # --- the paper ------------------------------------------------------------------

    def _list_paper_files(self, _: dict[str, Any]) -> Outcome:
        rows = [f"{self.label(p)} ({len(p.read_text(encoding='utf-8').splitlines())} lines)"
                for p in self.paper_files]
        return Outcome("list of paper files", "\n".join(rows))

    def label(self, path: Path) -> str:
        """A short, stable name for a paper file: its path inside the paper's build folder."""
        for parent in path.parents:
            if parent.name == "build":
                return path.relative_to(parent).as_posix()
        return path.name

    def _search_paper(self, arguments: dict[str, Any]) -> Outcome:
        phrase = str(arguments["phrase"]).strip().lower()
        if len(phrase) < 3:
            raise ValueError("Search for at least three characters.")
        hits: list[str] = []
        for path in self.paper_files:
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if phrase in line.lower():
                    hits.append(f"{self.label(path)}:{n}: {line.strip()[:200]}")
        shown = hits[:40]
        more = f"\n(and {len(hits) - 40} more)" if len(hits) > 40 else ""
        return Outcome(f"paper search for '{phrase}'",
                       "\n".join(shown) + more if shown else "No matches.")

    def _read_paper(self, arguments: dict[str, Any]) -> Outcome:
        name = str(arguments["file"])
        path = next((p for p in self.paper_files if self.label(p) == name), None)
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
        folder = self.workspace.root / ".scry-runs" / "claims"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"Claim{self.checks_run}.lean"
        path.write_text(f"import {self.solution_module}\n\n{code.strip()}\n", encoding="utf-8")
        check = check_file(self.workspace, path, CHECK_THEOREM)
        problems = "\n".join(f"- {p}" for p in check.problems)
        verdict = ("Lean accepts the claim." if check.passed
                   else f"Lean does not accept the claim:\n{problems}")
        errors = "".join(f"\n  line {e.line - 2}: {e.text.strip().splitlines()[0][:200]}"
                         for e in check.errors()[:5])
        return Outcome(f"Lean check of claim {self.checks_run}: "
                       f"{'accepted' if check.passed else 'not accepted'}",
                       verdict + errors, CheckKind.LEAN, check.receipt.receipt_id)


def _span(arguments: dict[str, Any], total: int) -> tuple[int, int]:
    first = max(1, int(arguments["first_line"]))
    last = min(total, int(arguments["last_line"]), first + MAX_LINES - 1)
    if first > last:
        raise ValueError(f"There are only {total} lines.")
    return first, last
