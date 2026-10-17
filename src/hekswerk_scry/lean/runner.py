"""Running Lean on a file and reporting, in plain English, whether a theorem is proven.

This is the only module that creates results labelled as coming from Lean. A theorem
counts as proven ("Lean-checked") only when all of these hold:

1. Lean finishes within the time limit and reports no errors.
2. The proof doesn't use `sorry` (Lean's placeholder for a missing proof).
3. The proof relies on no axioms beyond Lean's standard three
   (propext, Classical.choice, Quot.sound).

Lean files are programs: compiling one can run code written in it. Only check files
you trust, or run Scry somewhere isolated.
"""

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from hekswerk_scry.core.hashing import fingerprint_data
from hekswerk_scry.lean.processes import run_program
from hekswerk_scry.lean.worker import worker_for
from hekswerk_scry.lean.workspace import LeanWorkspace
from hekswerk_scry.models.receipts import LeanRunEvidence, Receipt

STANDARD_AXIOMS = frozenset({"propext", "Classical.choice", "Quot.sound"})
LEAN_OPTIONS = ("-DautoImplicit=false", "-DrelaxedAutoImplicit=false")
DEFAULT_TIMEOUT_SECONDS = 900
RUNS_FOLDER = ".scry-runs"

_AXIOMS = re.compile(r"^'(?P<name>[^']+)' depends on axioms: \[(?P<axioms>[^\]]*)\]")
_NO_AXIOMS = re.compile(r"^'(?P<name>[^']+)' does not depend on any axioms")


@dataclass(frozen=True)
class LeanMessage:
    """One message from Lean. Lines count from 1; columns count characters from 0."""

    severity: str
    line: int
    column: int
    end_line: int | None
    end_column: int | None
    text: str

    @property
    def is_error(self) -> bool:
        return self.severity == "error"


@dataclass(frozen=True)
class LeanCheck:
    """The result of running Lean on one file for one theorem."""

    file: str
    theorem: str
    passed: bool
    problems: tuple[str, ...]
    messages: tuple[LeanMessage, ...]
    axioms: tuple[str, ...] | None
    other_output: tuple[str, ...]
    seconds: float
    receipt: Receipt

    def errors(self) -> tuple[LeanMessage, ...]:
        return tuple(message for message in self.messages if message.is_error)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_file(
    workspace: LeanWorkspace,
    path: Path,
    theorem: str,
    *,
    source_text: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    fresh: bool = False,
) -> LeanCheck:
    """Run Lean on `path` (or on `source_text`, if given) and judge `theorem`.

    The file is copied into the workspace with one line added at the end that asks Lean
    which axioms the theorem relies on. Line numbers in messages match the original.

    Lean runs in the kept-running process (`lean/worker.py`) unless `fresh` is set or it
    is switched off; then a new `lean` process runs. Either way the same code judges
    Lean's messages.
    """
    workspace.build_imports(path)
    text = source_text if source_text is not None else path.read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    run_dir = workspace.root / RUNS_FOLDER / digest[:16]
    run_dir.mkdir(parents=True, exist_ok=True)
    run_file = run_dir / "Check.lean"
    run_file.write_text(f"{text.rstrip()}\n\n#print axioms {theorem}\n", encoding="utf-8")

    worker = None if fresh else worker_for(workspace, run_file)
    command: list[str] = [str(workspace.lake), "env", "lean", "--json", *LEAN_OPTIONS,
                          str(run_file)]
    started = time.monotonic()
    if worker is not None:
        reply = worker.ask("check", run_file, theorem, timeout=timeout)
        command = list(reply.command)
        messages_json = (reply.result or {}).get("messages", [])
        stdout = "\n".join([*(json.dumps(m) for m in messages_json), *reply.printed])
        stderr, timed_out = "", reply.timed_out
        exit_code = None if reply.timed_out else 0
    else:
        stdout, stderr, timed_out, exit_code = _run_fresh(workspace, command, timeout)
    seconds = time.monotonic() - started
    evidence = LeanRunEvidence(
        command=tuple(command),
        exit_code=exit_code,
        timed_out=timed_out,
        output_sha256=hashlib.sha256((stdout + "\0" + stderr).encode("utf-8")).hexdigest(),
        seconds=seconds,
    )
    return _judged(workspace, path, theorem, digest, evidence, stdout, stderr, timeout)


def _run_fresh(
    workspace: LeanWorkspace, command: list[str], timeout: float
) -> tuple[str, str, bool, int | None]:
    done = run_program(command, cwd=workspace.root, env=workspace.environment(),
                       timeout=timeout)
    return done.stdout, done.stderr, done.timed_out, done.exit_code


def _judged(
    workspace: LeanWorkspace, path: Path, theorem: str, digest: str, evidence: LeanRunEvidence,
    stdout: str, stderr: str, timeout: float,
) -> LeanCheck:
    timed_out, seconds = evidence.timed_out, evidence.seconds
    messages, other = parse_output(stdout)
    other += tuple(line for line in stderr.splitlines() if line.strip())
    axioms = find_axioms(messages, theorem)
    problems = judge(messages, axioms, theorem, timed_out=timed_out, timeout=timeout)
    passed = not problems
    recorded = workspace.relative(path)
    summary = (
        f"Lean-checked: Lean accepts '{theorem}' with no errors, no sorry, and only the "
        "standard axioms."
        if passed
        else f"Not proven by Lean: {problems[0]}"
    )
    receipt = Receipt.from_lean_run(
        evidence,
        subject=f"theorem '{theorem}' in {recorded}",
        subject_fingerprint=fingerprint_data(
            {
                "file_sha256": digest,
                "theorem": theorem,
                "toolchain": workspace.toolchain,
                "mathlib": workspace.mathlib_revision,
                "options": list(LEAN_OPTIONS),
            }
        ),
        passed=passed,
        summary=summary,
    )
    return LeanCheck(
        file=recorded,
        theorem=theorem,
        passed=passed,
        problems=problems,
        messages=messages,
        axioms=axioms,
        other_output=other,
        seconds=seconds,
        receipt=receipt,
    )


def parse_output(stdout: str) -> tuple[tuple[LeanMessage, ...], tuple[str, ...]]:
    """Split Lean's `--json` output into messages and any other printed lines.

    Some Mathlib tactics print debugging lines that are not Lean messages; those are kept
    separately and never counted as errors.
    """
    messages: list[LeanMessage] = []
    other: list[str] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            other.append(line)
            continue
        if not isinstance(data, dict) or "severity" not in data or "pos" not in data:
            other.append(line)
            continue
        end = data.get("endPos") or {}
        messages.append(
            LeanMessage(
                severity=str(data["severity"]),
                line=int(data["pos"]["line"]),
                column=int(data["pos"]["column"]),
                end_line=int(end["line"]) if "line" in end else None,
                end_column=int(end["column"]) if "column" in end else None,
                text=str(data.get("data", "")),
            )
        )
    return tuple(messages), tuple(other)


def find_axioms(messages: tuple[LeanMessage, ...], theorem: str) -> tuple[str, ...] | None:
    """The axioms Lean says `theorem` relies on, or None if Lean didn't say."""
    for message in reversed(messages):
        found = _AXIOMS.match(message.text)
        if found and found["name"] == theorem:
            return tuple(a.strip() for a in found["axioms"].split(",") if a.strip())
        none_found = _NO_AXIOMS.match(message.text)
        if none_found and none_found["name"] == theorem:
            return ()
    return None


def judge(
    messages: tuple[LeanMessage, ...],
    axioms: tuple[str, ...] | None,
    theorem: str,
    *,
    timed_out: bool = False,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[str, ...]:
    """Plain-English reasons the theorem is not proven. Empty means it is."""
    if timed_out:
        return (f"Lean took longer than {timeout:.0f} seconds and was stopped.",)
    problems: list[str] = []
    errors = [m for m in messages if m.is_error]
    if errors:
        first = errors[0]
        problems.append(
            f"Lean reported {len(errors)} error(s). The first, at line {first.line}: "
            f"{_first_line(first.text)}"
        )
    if any("declaration uses 'sorry'" in m.text for m in messages):
        problems.append("The proof uses `sorry`, Lean's placeholder for a missing proof.")
    if axioms is None:
        if not errors:
            problems.append(f"Lean did not report on a theorem called '{theorem}' in this file.")
    else:
        extra = sorted(set(axioms) - STANDARD_AXIOMS)
        # After an error, Lean patches the broken spot with `sorry` itself, so `sorryAx`
        # then shows up even though the author never wrote `sorry`.
        if "sorryAx" in extra and not errors and not any("sorry" in p for p in problems):
            problems.append("The proof uses `sorry`, Lean's placeholder for a missing proof.")
        extra = [a for a in extra if a != "sorryAx"]
        if extra:
            problems.append(
                "The proof relies on axioms beyond Lean's standard three: " + ", ".join(extra) + "."
            )
    return tuple(problems)


def _first_line(text: str, limit: int = 240) -> str:
    line = text.strip().splitlines()[0] if text.strip() else "(no details)"
    return line if len(line) <= limit else line[: limit - 3] + "..."
