"""Statement audits: does a formal statement say what its paper claims?

Lean's check of a proof settles the formal statement and nothing more. An audit lines the
formal statement up against the paper: each assumption, quantifier, domain, constant and
conclusion the paper states, against what the Lean statement says. Lean settles what it
can (the statement's anatomy, red-flag probes, and small claims the helper writes); the
rest is the helper's reading, with citations to both the paper and the Lean, for a
person to judge.

For an `openai/math` comparator challenge, the paper folders are found through OpenAI's
scope note, but only the links are read, never the note's text: the notes are the answer
key used to judge audits (see `compare_with_scope_note`).
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hekswerk_scry.ai.openrouter import OpenRouterClient
from hekswerk_scry.ai.run_log import LOG_FORMAT, LOG_SUFFIX, LOG_VERSION, RunLog
from hekswerk_scry.ai.session import Session, Turn
from hekswerk_scry.ai.statement_tools import CHECK_THEOREM, VERDICTS, StatementToolbox
from hekswerk_scry.ai.tools import Evidence
from hekswerk_scry.lean import openai_math
from hekswerk_scry.lean.statement import read_statement
from hekswerk_scry.lean.workspace import workspace_for_file

AUDIT_PROMPT = f"""\
You are auditing a formal statement in Scry. A Lean proof of a theorem settles exactly the \
formal statement and nothing more. Your job is to find out whether the formal statement says \
what the paper claims: the same objects, assumptions, quantifiers, domains, constants and \
conclusion. Differences matter in both directions: Lean's statement may assume more, \
conclude less, cover only a special case, or rest on definitions that mean something other \
than the paper's words.

How you work:
- Read the Lean statement first (read_statement), then every project definition it relies \
on (read_definition). Do not trust a definition's name; read its body.
- Find the paper's own statement of the result (search_paper, read_paper). Quote it.
- Compare item by item. Be exact about quantifiers ("for all" against "there exists"), \
strict against non-strict inequalities, domains (naturals, integers, reals), ranges of \
parameters, constants, and what exactly is concluded.
- When a difference could be settled by Lean, settle it with check_lean_claim: for example \
derive a special case the paper says the result covers, or exhibit an example meeting the \
hypotheses. Name the claim `theorem {CHECK_THEOREM}`. A claim Lean accepts is evidence; one it \
rejects is not evidence of the opposite (your Lean may just be wrong), so say so.
- Cite evidence for every claim, in square brackets: [E3]. Paper quotes cite the paper \
lookup that showed them; Lean facts cite Lean's reading.
- Record every row of your point-by-point comparison with record_verdict before you write \
the report, pointing at the specific Lean lines each row is about. The table in your report \
must match the rows you recorded.
- {{proof_status}} Never say the paper's result is proven.

Finish with a report in this shape (Markdown):
1. **The paper's claim**, quoted, with its location.
2. **The formal statement**, in plain words.
3. **Point by point**: a table with columns Item | Paper says | Lean says | Verdict, where \
the verdict is one of: {", ".join(VERDICTS)}. Cite evidence in every row.
4. **Definitions a person should read closely**, and why.
5. **Lean checks you ran** and what each one shows.
6. **Overall**: what the formal result establishes about the paper's claim, in two or three \
sentences. This whole report is your reading, except where it cites a Lean check.

Use plain technical English. The challenge you are auditing:
{{overview}}
"""


PROVED_CHALLENGE = ("This statement is a comparator challenge: Lean has checked a proof of it, "
                    "and that proof settles the formal statement and nothing more.")
AUDIT_ROUNDS = 40
AUDIT_REQUEST = "Audit this formal statement against the paper, and finish with the report."


@dataclass
class Audit:
    challenge: str
    turn: Turn
    toolbox: StatementToolbox
    papers: tuple[str, ...]
    cost_usd: float


def paper_files_for(item: openai_math.Challenge) -> tuple[tuple[str, ...], list[Path]]:
    """The papers a challenge formalizes (found through its scope note's links), and their
    LaTeX files."""
    note = openai_math.scope_note(item)
    papers = openai_math.papers_of(note) if note else ()
    return papers, [path for paper in papers for path in openai_math.paper_source(paper)]


def audit_prompt(toolbox: StatementToolbox, item: openai_math.Challenge,
                 papers: tuple[str, ...], proof_status: str) -> str:
    overview = "\n".join([
        f"Challenge: {item.name}",
        f"Theorems: {', '.join(item.theorem_names)}",
        f"Lean statement file: {toolbox.workspace.relative(toolbox.statement_file)}",
        f"Paper(s): {', '.join(papers) or '(none found)'}",
        f"Paper files: {len(toolbox.paper_files)} LaTeX file(s); use list_paper_files.",
    ])
    return AUDIT_PROMPT.format(overview=overview, proof_status=proof_status)


def run_audit(client: OpenRouterClient, toolbox: StatementToolbox, prompt: str,
              name: str, papers: tuple[str, ...], log: RunLog | None = None,
              about: dict[str, Any] | None = None) -> Audit:
    """Run one audit. With a `log`, every step is written to it as it happens, starting
    with `about` (what the run is, for the people reading the log)."""
    session = Session(client=client, toolbox=toolbox, system_prompt=prompt,
                      max_rounds=AUDIT_ROUNDS)
    if log is not None:
        statement = toolbox.statement_file
        log.write("start", format=LOG_FORMAT, version=LOG_VERSION, challenge=name,
                  statement_file=toolbox.workspace.relative(statement),
                  statement_text=statement.read_text(encoding="utf-8"),
                  theorems=list(toolbox.reports), papers=list(papers),
                  model=client.settings.model, effort=client.settings.effort,
                  **(about or {}))
        spent = [0.0]

        def on_reply(text: str, tools: list[str], cost: float) -> None:
            spent[0] += cost
            log.write("model", text=text, tool_calls=tools, cost_usd=round(cost, 6),
                      cost_so_far_usd=round(spent[0], 6))

        def on_evidence(item: Evidence) -> None:
            rows = len(toolbox.verdicts)
            log.evidence(item)
            if item.tool == "record_verdict" and rows and item.summary.startswith(
                    f"verdict {rows}:"):
                log.write("verdict", number=rows, evidence_id=item.evidence_id,
                          **vars(toolbox.verdicts[-1]))

        session.on_reply, session.on_evidence = on_reply, on_evidence
    try:
        turn = session.ask(AUDIT_REQUEST)
    except BaseException as exc:
        if log is not None:
            log.write("stopped", reason=f"{type(exc).__name__}: {exc}",
                      cost_usd=round(session.total_cost_usd, 6))
        raise
    audit = Audit(name, turn, toolbox, papers, session.total_cost_usd)
    if log is not None:
        log.write("finish", answer=turn.answer, cost_usd=round(audit.cost_usd, 6),
                  hit_round_limit=turn.hit_round_limit,
                  cited=[e.evidence_id for e in turn.cited],
                  unknown_citations=turn.unknown_citations)
    return audit


def audit_challenge(client: OpenRouterClient, name: str, log_folder: Path | None = None) -> Audit:
    item = openai_math.challenge(name)
    workspace = workspace_for_file(item.statement_file)
    papers, paper_files = paper_files_for(item)
    reports = {theorem: read_statement(workspace, item.statement_file, theorem)
               for theorem in item.theorem_names}
    toolbox = StatementToolbox(
        workspace=workspace, statement_file=item.statement_file,
        solution_module=item.solution_module, reports=reports, paper_files=paper_files,
    )
    prompt = audit_prompt(toolbox, item, papers, PROVED_CHALLENGE)
    log = None
    if log_folder is not None:
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        log = RunLog(log_folder / f"{item.name}-{stamp}{LOG_SUFFIX}")
    return run_audit(client, toolbox, prompt, item.name, papers, log,
                     {"title": f"Statement audit of {item.name}", "copy": None})


def compare_with_scope_note(name: str, audit_text: str) -> str:
    """The audit next to OpenAI's own scope note, for a person to compare."""
    note = openai_math.scope_note(openai_math.challenge(name))
    note_text = (note.read_text(encoding="utf-8") if note
                 else "(OpenAI wrote no scope note for this.)")
    return "\n".join([
        f"# Statement audit of {name}, next to OpenAI's scope note", "",
        "## Scry's audit (the AI helper's reading, except where it cites a Lean check)", "",
        audit_text.strip(), "",
        f"## OpenAI's scope note ({note.name if note else 'none'}), not seen by the helper", "",
        note_text.strip(), "",
    ])


def audit_text(audit: Audit) -> str:
    """The helper's report, then the rows it recorded and the evidence it gathered."""
    evidence = "\n".join(f"- {e.label}" for e in audit.toolbox.evidence)
    rows = "\n".join(
        f"| {r.item} | {r.verdict} | {'yes' if r.affects_main_result else 'no'} | "
        f"{f'{r.lean_lines[0]}-{r.lean_lines[1]}' if r.lean_lines else '-'} | "
        f"{', '.join(r.evidence)} |"
        for r in audit.toolbox.verdicts
    ) or "| (no rows recorded) | | | | |"
    return "\n".join([
        audit.turn.answer.strip(), "",
        "## Rows the helper recorded", "",
        "| Item | Verdict | Affects main result | Lean lines | Evidence |",
        "| --- | --- | --- | --- | --- |", rows, "",
        "## Evidence", "", evidence, "",
        f"(Cost of this audit: ${audit.cost_usd:.4f}.)", "",
    ])


def save_audit(audit: Audit, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    text = audit_text(audit)
    path = folder / f"{audit.challenge}.md"
    path.write_text(compare_with_scope_note(audit.challenge, text), encoding="utf-8")
    return path
