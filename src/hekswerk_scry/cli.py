"""The `scry` command line: check, scan, and poke at proof maps.

    scry demo                                    walk through the bundled example
    scry check MAP.json                          run the wiring check
    scry scan MAP.json                           find chokepoints, knots, and unused steps
    scry what-if MAP.json --remove-step ID       see what relies on a step
    scry what-if MAP.json --drop-fact "FACT"     see what relies on a starting fact

With Lean (see "Setting up Lean" in README.md):

    scry lean-demo                               walk through the example, checked by Lean
    scry fetch-alphaproof                        download DeepMind's AlphaProof proofs
    scry lean-import FILE.lean THEOREM -o MAP.json   turn a Lean proof into a proof map
    scry lean-check MAP.json                     ask Lean whether the theorem is proven
    scry what-if MAP.json --remove-step ID --lean    make a step do nothing; Lean judges
    scry lean-region MAP.json --fact ID          show what re-proving a fact would replace
    scry lean-card MAP.json --fact ID --tactics FILE [--apply NEW.lean --save-map NEW.json]
                                                 re-prove a fact with new tactics; Lean judges
    scry lean-statement FILE.lean THEOREM [--no-probes]
                                                 what a theorem states, and Lean's red-flag probes

OpenAI's mathematics repository (github.com/openai/math):

    scry fetch-openai-math                       clone its Lean formalizations
    scry openai-challenges                       list its comparator challenges
    scry openai-challenge NAME [--no-probes]     what one formal result states
    scry audit-statement NAME [--out FOLDER]     the AI helper lines the statement up against
                                                 its paper; saved next to OpenAI's scope note
    scry statement-benchmark [NAME ...] [--prepare-only] [--out FOLDER]
                                                 audit unchanged and planted copies of
                                                 statements blind, and score the audits

With an OpenRouter key in .env (see "The AI helper" in README.md):

    scry chat MAP.json                           work on a proof with the AI helper
"""

import argparse
import sys
import textwrap
from collections.abc import Sequence
from pathlib import Path

from hekswerk_scry.ai.audit import audit_challenge, save_audit
from hekswerk_scry.ai.benchmark import (
    DEFAULT_BUDGET_USD,
    BenchmarkError,
    load_plants,
    prepare,
    run_benchmark,
)
from hekswerk_scry.ai.openrouter import AIProviderError, OpenRouterClient
from hekswerk_scry.ai.session import Session
from hekswerk_scry.ai.tools import Toolbox
from hekswerk_scry.checker import (
    apply_card,
    check_card,
    check_wiring,
    run_what_if,
    scan_proof_map,
)
from hekswerk_scry.core.enums import CardStatus, WhatIfKind
from hekswerk_scry.core.settings import load_ai_settings
from hekswerk_scry.examples import load_example
from hekswerk_scry.files import load_proof_map, save_proof_map
from hekswerk_scry.lean import openai_math
from hekswerk_scry.lean.alphaproof import AlphaProofFetchError, fetch_alphaproof
from hekswerk_scry.lean.cards import (
    LeanCardRejectedError,
    apply_lean_card,
    check_lean_card,
    draft_lean_card,
    find_region,
)
from hekswerk_scry.lean.checks import check_map_with_lean, source_path, workspace_of
from hekswerk_scry.lean.importer import LeanImportError, import_theorem
from hekswerk_scry.lean.statement import StatementError, read_statement
from hekswerk_scry.lean.what_if import run_lean_what_if
from hekswerk_scry.lean.worker import LeanWorkerError
from hekswerk_scry.lean.workspace import LeanSetupError, find_workspace, workspace_for_file
from hekswerk_scry.models import (
    ProofMap,
    ProofStep,
    SimplificationCard,
    StepContract,
    StepViews,
    WhatIfChange,
)
from hekswerk_scry.text_reports import (
    render_breakage,
    render_card_check,
    render_history,
    render_lean_card_check,
    render_lean_region,
    render_lean_report,
    render_map_overview,
    render_scan,
    render_statement,
    render_turn,
    render_wiring_report,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            return run_demo()
        if args.command == "check":
            return _check(Path(args.map_file))
        if args.command == "scan":
            return _scan(Path(args.map_file))
        if args.command == "what-if":
            return _what_if(Path(args.map_file), args.remove_step, args.drop_fact, args.lean)
        if args.command == "lean-import":
            return _lean_import(Path(args.lean_file), args.theorem, Path(args.out))
        if args.command == "lean-check":
            return _lean_check(Path(args.map_file))
        if args.command == "fetch-alphaproof":
            return _fetch_alphaproof()
        if args.command == "lean-demo":
            return run_lean_demo()
        if args.command == "lean-region":
            return _lean_region(Path(args.map_file), args.fact)
        if args.command == "lean-card":
            return _lean_card(args)
        if args.command == "chat":
            return _chat(Path(args.map_file))
        if args.command == "lean-statement":
            return _lean_statement(Path(args.lean_file), args.theorem, not args.no_probes)
        if args.command == "fetch-openai-math":
            print(f"openai/math is at {openai_math.fetch()}. Next: `make openai-setup`.")
            return 0
        if args.command == "openai-challenges":
            return _openai_challenges()
        if args.command == "openai-challenge":
            return _openai_challenge(args.name, not args.no_probes)
        if args.command == "audit-statement":
            return _audit_statement(args.name, Path(args.out))
        if args.command == "statement-benchmark":
            return _statement_benchmark(args.names, Path(args.out), args.prepare_only,
                                        args.budget)
    except (ValueError, LeanSetupError, LeanImportError, LeanWorkerError, BenchmarkError,
            AlphaProofFetchError,
            AIProviderError, StatementError, openai_math.OpenAIMathError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scry",
        description="A plain-English workbench for untangling convoluted proofs.",
    )
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("demo", help="walk through the bundled example proof")
    check = commands.add_parser("check", help="run the wiring check on a proof map file")
    check.add_argument("map_file", help="path to a proof map JSON file")
    scan = commands.add_parser("scan", help="find chokepoints, knots, and unused steps")
    scan.add_argument("map_file", help="path to a proof map JSON file")
    what_if = commands.add_parser("what-if", help="remove something and see what breaks")
    what_if.add_argument("map_file", help="path to a proof map JSON file")
    change = what_if.add_mutually_exclusive_group(required=True)
    change.add_argument("--remove-step", metavar="STEP_ID", help="remove this step")
    change.add_argument("--drop-fact", metavar="FACT", help="drop this starting fact")
    what_if.add_argument(
        "--lean", action="store_true", help="let Lean judge the change (Lean-backed maps only)"
    )
    lean_import = commands.add_parser("lean-import", help="turn a Lean proof into a proof map")
    lean_import.add_argument("lean_file", help="path to a .lean file")
    lean_import.add_argument("theorem", help="the theorem's full name")
    lean_import.add_argument("-o", "--out", required=True, help="where to save the proof map")
    lean_check = commands.add_parser("lean-check", help="ask Lean whether the theorem is proven")
    lean_check.add_argument("map_file", help="path to a Lean-backed proof map JSON file")
    commands.add_parser("fetch-alphaproof", help="download DeepMind's AlphaProof proofs")
    commands.add_parser("lean-demo", help="walk through the example, checked by Lean")
    region = commands.add_parser("lean-region", help="show what re-proving a fact would replace")
    region.add_argument("map_file", help="path to a Lean-backed proof map JSON file")
    region.add_argument(
        "--fact", required=True, metavar="STEP_ID", help="the step whose fact to re-prove"
    )
    card = commands.add_parser("lean-card", help="re-prove a fact with new tactics; Lean judges")
    card.add_argument("map_file", help="path to a Lean-backed proof map JSON file")
    card.add_argument(
        "--fact", required=True, metavar="STEP_ID", help="the step whose fact to re-prove"
    )
    card.add_argument("--tactics", required=True, metavar="FILE",
                      help="file with the new Lean tactics ('-' to read them from input)")
    card.add_argument("--title", default="", help="a short name for the card")
    card.add_argument("--why", default="", help="why the new proof is better, in plain words")
    card.add_argument("--apply", metavar="NEW.lean",
                      help="if Lean accepts the card, write the changed proof to this new file")
    card.add_argument("--save-map", metavar="NEW.json",
                      help="with --apply: save the changed proof's map here")
    chat = commands.add_parser("chat", help="work on a proof with the AI helper")
    chat.add_argument("map_file", help="path to a proof map JSON file")
    statement = commands.add_parser("lean-statement", help="what a theorem states")
    statement.add_argument("lean_file", help="path to a .lean file")
    statement.add_argument("theorem", help="the theorem's full name")
    statement.add_argument("--no-probes", action="store_true", help="skip Lean's probes")
    commands.add_parser("fetch-openai-math", help="clone openai/math's Lean formalizations")
    commands.add_parser("openai-challenges", help="list openai/math's comparator challenges")
    one = commands.add_parser("openai-challenge", help="what one openai/math result states")
    one.add_argument("name", help="the challenge's name, such as TruffetCounterexample")
    one.add_argument("--no-probes", action="store_true", help="skip Lean's probes")
    audit = commands.add_parser("audit-statement",
                                help="line an openai/math statement up against its paper")
    audit.add_argument("name", help="the comparator challenge's name")
    audit.add_argument("--out", default="audits", help="folder for the report (default: audits)")
    bench = commands.add_parser("statement-benchmark",
                                help="score statement audits on copies with planted differences")
    bench.add_argument("names", nargs="*", help="challenges to use (default: every one with "
                       "plants in benchmarks/statement-plants.json)")
    bench.add_argument("--prepare-only", action="store_true",
                       help="make and Lean-check the copies, without calling the model")
    bench.add_argument("--budget", type=float, default=DEFAULT_BUDGET_USD,
                       help="stop before an audit that could take the spend past this many "
                       f"US dollars (default {DEFAULT_BUDGET_USD:.2f})")
    bench.add_argument("--out", default="audits/benchmark",
                       help="folder for the results (default: audits/benchmark)")
    return parser


def _check(path: Path) -> int:
    proof_map = load_proof_map(path)
    report = check_wiring(proof_map)
    print(render_wiring_report(proof_map, report))
    return 0 if report.passed else 1


def _scan(path: Path) -> int:
    print(render_scan(scan_proof_map(load_proof_map(path))))
    return 0


def _what_if(path: Path, remove_step: str | None, drop_fact: str | None, lean: bool) -> int:
    proof_map = load_proof_map(path)
    if remove_step is not None:
        change = WhatIfChange(WhatIfKind.REMOVE_STEP, remove_step)
    else:
        change = WhatIfChange(WhatIfKind.DROP_STARTING_FACT, drop_fact or "")
    if lean:
        if proof_map.lean_source is None:
            raise ValueError(
                f"'{path}' was not made from a Lean file, so Lean can't judge the change. "
                "Leave out --lean to run a wiring What-If test instead."
            )
        print(render_breakage(run_lean_what_if(workspace_of(proof_map), proof_map, change)))
    else:
        print(render_breakage(run_what_if(proof_map, change)))
    return 0


def _lean_import(lean_file: Path, theorem: str, out: Path) -> int:
    proof_map = import_theorem(workspace_for_file(lean_file), lean_file, theorem)
    save_proof_map(proof_map, out)
    print(f"Saved a proof map of '{theorem}' with {len(proof_map.steps)} steps to {out}.")
    print(textwrap.fill(check_wiring(proof_map).summary, 92, initial_indent="  ",
                        subsequent_indent="  "))
    print()
    print(render_scan(scan_proof_map(proof_map)))
    return 0


def _lean_check(path: Path) -> int:
    proof_map = load_proof_map(path)
    if proof_map.lean_source is None:
        raise ValueError(
            f"'{path}' was not made from a Lean file, so Lean can't check it. "
            "Make a Lean-backed map with `scry lean-import`."
        )
    report = check_map_with_lean(workspace_of(proof_map), proof_map)
    print(render_lean_report(proof_map, report))
    return 0 if report.passed else 1


def _lean_map(path: Path) -> ProofMap:
    proof_map = load_proof_map(path)
    if proof_map.lean_source is None:
        raise ValueError(
            f"'{path}' was not made from a Lean file. Make one with `scry lean-import`."
        )
    return proof_map


def _lean_region(path: Path, fact: str) -> int:
    proof_map = _lean_map(path)
    workspace = workspace_of(proof_map)
    _, lean_file = source_path(workspace, proof_map)
    text = lean_file.read_text(encoding="utf-8")
    print(render_lean_region(proof_map, find_region(proof_map, text, fact), text))
    return 0


def _lean_card(args: argparse.Namespace) -> int:
    proof_map = _lean_map(Path(args.map_file))
    if args.save_map and not args.apply:
        raise ValueError("--save-map only makes sense together with --apply.")
    tactics = sys.stdin.read() if args.tactics == "-" else Path(args.tactics).read_text(
        encoding="utf-8"
    )
    workspace = workspace_of(proof_map)
    card = draft_lean_card(
        workspace, proof_map, args.fact,
        card_id=f"reprove-{args.fact}", title=args.title or f"Re-prove {args.fact}",
        why=args.why, replacement=tactics,
    )
    check = check_lean_card(workspace, proof_map, card)
    print(render_lean_card_check(card, check))
    if check.status is not CardStatus.READY_TO_SWAP:
        return 1
    if args.apply:
        try:
            new_map, _receipt = apply_lean_card(workspace, proof_map, card, Path(args.apply))
        except LeanCardRejectedError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(f"\nApplied. The changed proof is in {args.apply} "
              f"({len(new_map.steps)} steps); the original file is untouched.")
        if args.save_map:
            save_proof_map(new_map, Path(args.save_map))
            print(f"Its map, with the replaced steps archived, is in {args.save_map}.")
    return 0


CHAT_HELP = """Commands:
  /cards               list the cards the helper has drafted, with Lean's verdict
  /apply CARD NEW.lean apply a card the helper drafted (Lean checks it again first)
  /evidence E3         show one piece of evidence in full
  /cost                show what this conversation has cost so far
  /quit                leave
Anything else is sent to the helper."""


def _chat(path: Path) -> int:
    proof_map = load_proof_map(path)
    settings = load_ai_settings()
    workspace = workspace_of(proof_map) if proof_map.lean_source is not None else None
    toolbox = Toolbox(proof_map=proof_map, workspace=workspace)
    session = Session(client=OpenRouterClient(settings), toolbox=toolbox)
    print(f"Talking about '{proof_map.title}' with {settings.model} (effort {settings.effort}).")
    print("Answers are the helper's reading; only Lean's checks count as proof.")
    print(CHAT_HELP)
    while True:
        try:
            line = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in ("/quit", "/exit"):
            return 0
        if line.startswith("/"):
            print(_chat_command(line, toolbox, session, proof_map))
            continue
        print("\n(thinking and checking...)")
        try:
            print(render_turn(session.ask(line)))
        except AIProviderError as exc:
            print(f"Error: {exc}")


def _chat_command(line: str, toolbox: Toolbox, session: Session, proof_map: ProofMap) -> str:
    command, *rest = line.split()
    if command == "/cards":
        if not toolbox.cards:
            return "The helper hasn't drafted any cards yet."
        return "\n".join(
            f"{card_id}: re-proves {d.card.fact_step_id} | {d.check.status.label} | evidence "
            f"{d.evidence_id}" for card_id, d in toolbox.cards.items()
        )
    if command == "/evidence" and len(rest) == 1:
        found = next((e for e in toolbox.evidence if e.evidence_id == rest[0]), None)
        return f"{found.label}\n{found.result}" if found else f"There is no evidence {rest[0]}."
    if command == "/cost":
        return f"This conversation has cost ${session.total_cost_usd:.4f} so far."
    if command == "/apply" and len(rest) == 2:
        drafted = toolbox.cards.get(rest[0])
        if drafted is None:
            return f"There is no card {rest[0]}. See /cards."
        if toolbox.workspace is None:
            return "Lean is not available for this map."
        try:
            new_map, _ = apply_lean_card(toolbox.workspace, proof_map, drafted.card, Path(rest[1]))
        except (LeanCardRejectedError, ValueError) as exc:
            return f"Not applied: {exc}"
        saved = Path(rest[1]).with_suffix(".json")
        save_proof_map(new_map, saved)
        return (f"Applied {rest[0]}. Lean checked it again. The changed proof is in {rest[1]} and "
                f"its map in {saved}. The original file is untouched; this conversation keeps "
                "working on the original map.")
    return CHAT_HELP


def _lean_statement(lean_file: Path, theorem: str, probes: bool) -> int:
    report = read_statement(workspace_for_file(lean_file), lean_file, theorem, probes=probes)
    print(render_statement(report))
    return 1 if report.red_flags else 0


def _openai_challenges() -> int:
    items = openai_math.challenges()
    for item in items:
        tag = "  (supporting result)" if item.is_supporting_result else ""
        print(f"{item.name}{tag}: {', '.join(item.theorem_names)}")
    print(f"\n{len(items)} challenges. `scry openai-challenge NAME` shows what one states.")
    return 0


def _openai_challenge(name: str, probes: bool) -> int:
    item = openai_math.challenge(name)
    workspace = workspace_for_file(item.statement_file)
    print(f"Comparator challenge {item.name}")
    print(f"  Statement: {workspace.relative(item.statement_file)}")
    print(f"  Proved in: {item.solution_module} ({workspace.relative(item.solution_file)})")
    print(f"  Permitted axioms: {', '.join(item.permitted_axioms)}\n")
    flagged = False
    for theorem in item.theorem_names:
        report = read_statement(workspace, item.statement_file, theorem, probes=probes)
        print(render_statement(report))
        print()
        flagged = flagged or bool(report.red_flags)
    return 1 if flagged else 0


def _audit_statement(name: str, out: Path) -> int:
    settings = load_ai_settings()
    print(f"Auditing {name} with {settings.model} (effort {settings.effort}). Reading the "
          "statement with Lean first; this can take several minutes.")
    result = audit_challenge(OpenRouterClient(settings), name)
    print(render_turn(result.turn))
    path = save_audit(result, out)
    print(f"\nSaved the audit next to OpenAI's scope note (which the helper did not see): {path}")
    return 0


def _statement_benchmark(names: list[str], out: Path, prepare_only: bool,
                         budget: float) -> int:
    plants = load_plants()
    names = names or sorted(plants)
    count = sum(1 + len(plants.get(n, [])) for n in names)
    if prepare_only:
        prepared = prepare(names, plants)
        for variant, _, _ in prepared:
            where = (f"planted at line(s) {variant.planted_lines[0]}-{variant.planted_lines[1]}"
                     if variant.planted_lines else "unchanged")
            print(f"Lean accepts the {variant.name} copy of {variant.item.name} ({where}).")
        print(f"\n{len(prepared)} copies ready. Run without --prepare-only to audit them.")
        return 0
    settings = load_ai_settings()
    print(f"Auditing {count} copies of {len(names)} statements with {settings.model} (effort "
          f"{settings.effort}). Each audit is a separate conversation; so far they have cost "
          "$0.40 to $1.50 each, more when the scope note links many papers. Audits saved "
          f"in {out} for identical copies are reused.")
    print(f"Budget: ${budget:.2f}; the run stops before an audit that could go past it.")
    summary = run_benchmark(OpenRouterClient(settings), names, out, plants, budget)
    print(summary.read_text(encoding="utf-8"))
    print(f"\nSaved in {summary.parent}.")
    return 0


def _fetch_alphaproof() -> int:
    workspace = find_workspace()
    files = fetch_alphaproof(workspace)
    print("Downloaded DeepMind's AlphaProof proofs from IMO 2024 (fingerprint checked):")
    for path, theorem in files.items():
        print(f"  {workspace.relative(path)}  (theorem {theorem})")
    first, theorem = next(iter(files.items()))
    print("\nTo make a proof map of one, for example:")
    print(f"  scry lean-import {path_hint(first)} {theorem} -o {theorem}.json")
    return 0


def path_hint(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def _section(title: str) -> None:
    print()
    print("=" * 92)
    print(title)
    print("=" * 92)


def run_demo() -> int:
    """Walk through the bundled example, one feature at a time."""
    proof_map = load_example("shifted_fraction")

    _section("1. The example proof")
    print(render_map_overview(proof_map))
    print(
        "\n  It proves a simple fact the long way round, the way machine-written proofs\n"
        "  often do: it shows x + 7 is positive by going through cubes and squares."
    )

    _section("2. Wiring check: do the facts feed into each other correctly?")
    print(render_wiring_report(proof_map, check_wiring(proof_map)))

    _section("3. Scan: where should a person look first?")
    scan = scan_proof_map(proof_map)
    print(render_scan(scan))

    _section("4. What-If tests: what relies on what?")
    for change in (
        WhatIfChange(WhatIfKind.REMOVE_STEP, "cube-split"),
        WhatIfChange(WhatIfKind.DROP_STARTING_FACT, "x >= 0"),
        WhatIfChange(WhatIfKind.REMOVE_STEP, "square-nonneg"),
    ):
        print(render_breakage(run_what_if(proof_map, change)))
        print()

    knot = next(iter(scan.knots), None)
    if knot is None:
        print("The scan found no knot to simplify, so the demo stops here.")
        return 0

    _section("5. A card that tries to sneak in a new assumption")
    cheating = SimplificationCard.draft(
        proof_map,
        card_id="assume-x-positive",
        title="Just assume x is positive",
        why="If x > 0 then x + 7 > 0 at once.",
        region_step_ids=knot.step_ids,
        replacement_steps=[
            ProofStep(
                step_id="shift-positive-assumed",
                title="x + 7 is positive because x is",
                contract=StepContract(assumes=("x > 0",), proves="x + 7 > 0"),
            )
        ],
    )
    print(render_card_check(cheating, check_card(proof_map, cheating)))

    _section("6. An honest card: same inputs, same result, fewer steps")
    honest = SimplificationCard.draft(
        proof_map,
        card_id="direct-shift",
        title="Show x + 7 > 0 directly",
        why=(
            "The four steps only exist to show x + 7 > 0, and that follows straight "
            "from x >= 0."
        ),
        region_step_ids=knot.step_ids,
        replacement_steps=[
            ProofStep(
                step_id="shift-positive-direct",
                title="x + 7 is positive",
                contract=StepContract(assumes=("x >= 0",), proves="x + 7 > 0"),
                views=StepViews(
                    plain_english="Since x is at least 0, x + 7 is at least 7, which is positive.",
                    math="x >= 0  =>  x + 7 > 0",
                    code="have shift_pos : x + 7 > 0 := by linarith",
                ),
            )
        ],
    )
    print(render_card_check(honest, check_card(proof_map, honest)))
    simpler, _receipt = apply_card(proof_map, honest)

    _section("7. After the swap")
    print(render_wiring_report(simpler, check_wiring(simpler)))
    print()
    print(render_scan(scan_proof_map(simpler)))
    print("\nHistory:")
    print(render_history(simpler))
    print(
        "\nEverything above is 'wiring checked (not proven)'. Next, Lean will check the\n"
        "math of each step; until then, nothing here counts as proven."
    )
    return 0


def run_lean_demo() -> int:
    """Walk through the Lean version of the example: import, check, scan, What-If."""
    workspace = find_workspace()
    lean_file = workspace.root / "Examples" / "ShiftedFraction.lean"
    _section("1. Turn the Lean proof into a proof map")
    proof_map = import_theorem(workspace, lean_file, "shifted_fraction_ne_one")
    print(render_map_overview(proof_map))
    print(
        "\n  Every step, and every arrow between steps, comes from Lean's own record of the\n"
        "  finished proof: which goal each tactic worked on, and what its part relied on."
    )

    _section("2. Ask Lean whether the theorem is proven")
    print(render_lean_report(proof_map, check_map_with_lean(workspace, proof_map)))

    _section("3. Scan: where should a person look first?")
    print(render_scan(scan_proof_map(proof_map)))

    _section("4. What-If tests, judged by Lean")
    for step_id in ("s10", "s3"):
        change = WhatIfChange(WhatIfKind.REMOVE_STEP, step_id)
        print(render_breakage(run_lean_what_if(workspace, proof_map, change)))
        print()

    _section("5. A Simplification card: prove shift_pos directly, and let Lean judge")
    text = lean_file.read_text(encoding="utf-8")
    print(render_lean_region(proof_map, find_region(proof_map, text, "s7-why1"), text))
    print()
    card = draft_lean_card(
        workspace, proof_map, "s7-why1",
        card_id="direct-shift", title="Show x + 7 > 0 directly",
        why="x >= 0 gives x + 7 > 0 at once; the cubes and squares were a detour.",
        replacement="-- x is at least 0, so x + 7 is at least 7.\nlinarith",
    )
    print(render_lean_card_check(card, check_lean_card(workspace, proof_map, card)))
    print(
        "\n  To write the simpler proof to a new file (the original is never touched):\n"
        "    scry lean-card MAP.json --fact s7-why1 --tactics TACTICS.lean --apply NEW.lean"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
