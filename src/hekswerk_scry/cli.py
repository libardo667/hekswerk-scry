"""The `scry` command line: check, scan, and poke at proof maps.

    scry demo                                    walk through the bundled example
    scry check MAP.json                          run the wiring check
    scry scan MAP.json                           find chokepoints, knots, and unused steps
    scry what-if MAP.json --remove-step ID       see what relies on a step
    scry what-if MAP.json --drop-fact "FACT"     see what relies on a starting fact
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from hekswerk_scry.checker import (
    apply_card,
    check_card,
    check_wiring,
    run_what_if,
    scan_proof_map,
)
from hekswerk_scry.core.enums import WhatIfKind
from hekswerk_scry.examples import load_example
from hekswerk_scry.files import load_proof_map
from hekswerk_scry.models import (
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
    render_map_overview,
    render_scan,
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
            return _what_if(Path(args.map_file), args.remove_step, args.drop_fact)
    except ValueError as exc:
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
    return parser


def _check(path: Path) -> int:
    proof_map = load_proof_map(path)
    report = check_wiring(proof_map)
    print(render_wiring_report(proof_map, report))
    return 0 if report.passed else 1


def _scan(path: Path) -> int:
    print(render_scan(scan_proof_map(load_proof_map(path))))
    return 0


def _what_if(path: Path, remove_step: str | None, drop_fact: str | None) -> int:
    proof_map = load_proof_map(path)
    if remove_step is not None:
        change = WhatIfChange(WhatIfKind.REMOVE_STEP, remove_step)
    else:
        change = WhatIfChange(WhatIfKind.DROP_STARTING_FACT, drop_fact or "")
    print(render_breakage(run_what_if(proof_map, change)))
    return 0


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


if __name__ == "__main__":
    raise SystemExit(main())
