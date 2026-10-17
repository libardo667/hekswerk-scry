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

from dataclasses import dataclass
from pathlib import Path

from hekswerk_scry.ai.openrouter import OpenRouterClient
from hekswerk_scry.ai.session import Session, Turn
from hekswerk_scry.ai.statement_tools import CHECK_THEOREM, StatementToolbox
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
- Never say the paper's result is proven. At most: the formal statement is proven (it is, if \
it is a comparator challenge), and it does or does not match the paper on each point.

Finish with a report in this shape (Markdown):
1. **The paper's claim**, quoted, with its location.
2. **The formal statement**, in plain words.
3. **Point by point**: a table with columns Item | Paper says | Lean says | Verdict, where \
the verdict is one of: matches, Lean assumes more, Lean concludes less, Lean covers a \
special case, differs, not in the formalization, unclear. Cite evidence in every row.
4. **Definitions a person should read closely**, and why.
5. **Lean checks you ran** and what each one shows.
6. **Overall**: what the formal result establishes about the paper's claim, in two or three \
sentences. This whole report is your reading, except where it cites a Lean check.

Use plain technical English. The challenge you are auditing:
{{overview}}
"""


@dataclass
class Audit:
    challenge: str
    turn: Turn
    toolbox: StatementToolbox
    papers: tuple[str, ...]
    cost_usd: float


def audit_challenge(client: OpenRouterClient, name: str) -> Audit:
    item = openai_math.challenge(name)
    workspace = workspace_for_file(item.statement_file)
    note = openai_math.scope_note(item)
    papers = openai_math.papers_of(note) if note else ()
    paper_files = [path for paper in papers for path in openai_math.paper_source(paper)]
    reports = {theorem: read_statement(workspace, item.statement_file, theorem)
               for theorem in item.theorem_names}
    toolbox = StatementToolbox(
        workspace=workspace, statement_file=item.statement_file,
        solution_module=item.solution_module, reports=reports, paper_files=paper_files,
    )
    overview = "\n".join([
        f"Challenge: {item.name}",
        f"Theorems: {', '.join(item.theorem_names)}",
        f"Lean statement file: {workspace.relative(item.statement_file)}",
        f"Proved in: {item.solution_module}",
        f"Paper(s): {', '.join(papers) or '(none found)'}",
        f"Paper files: {len(paper_files)} LaTeX file(s); use list_paper_files.",
    ])
    session = Session(client=client, toolbox=toolbox,
                      system_prompt=AUDIT_PROMPT.format(overview=overview))
    turn = session.ask(
        "Audit this formal statement against the paper, and finish with the report."
    )
    return Audit(item.name, turn, toolbox, papers, session.total_cost_usd)


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


def save_audit(audit: Audit, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    evidence = "\n".join(f"- {e.label}" for e in audit.toolbox.evidence)
    text = "\n".join([
        audit.turn.answer.strip(), "", "## Evidence", "", evidence, "",
        f"(Cost of this audit: ${audit.cost_usd:.4f}.)", "",
    ])
    path = folder / f"{audit.challenge}.md"
    path.write_text(compare_with_scope_note(audit.challenge, text), encoding="utf-8")
    return path
