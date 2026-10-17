"""What a theorem actually states, read by Lean, and the Lean probes for red flags.

Lean's check of a proof settles the *formal* statement, and only that. Whether the formal
statement says what a paper claims is a separate question. This module reports the parts
of the answer that Lean itself can give:

- the statement's hypotheses, its conclusion, and every project-specific definition it
  depends on (definitions are where meaning can quietly differ from the paper);
- two probes: whether the hypotheses contradict each other (so the theorem says nothing),
  and whether the conclusion follows without them. A probe counts only when a standard
  tactic finds a proof and the Lean kernel accepts it. When the tactics find nothing, that
  is reported as exactly that, never as evidence that all is well.

Reading a statement means loading the file's imports (often all of Mathlib), which takes
minutes. Each run's result is stored in the project's run folder, keyed by everything that
could change Lean's answer: the file's exact contents, the theorem, the Lean version, the
exporter build, and whether probes ran. A stored result is marked as reused, with the time
of the Lean run it came from.
"""

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from hekswerk_scry.core.hashing import fingerprint_data
from hekswerk_scry.lean.workspace import LeanWorkspace
from hekswerk_scry.models.receipts import LeanRunEvidence, Receipt

STATEMENT_FORMAT = "hekswerk-scry/lean-statement"
TIMEOUT_SECONDS = 3600
STORE_FOLDER = Path(".scry-runs") / "statements"


class StatementError(RuntimeError):
    """Lean couldn't report on the statement. The message says why."""


@dataclass(frozen=True)
class Binder:
    name: str
    type: str
    binder: str
    is_prop: bool


@dataclass(frozen=True)
class ProjectDefinition:
    """A definition from the project (not from Lean or Mathlib) the statement relies on.

    `depth` 1 means the statement mentions it directly; 2 means a depth-1 definition
    mentions it; and so on.
    """

    name: str
    kind: str
    depth: int
    type: str
    value: str | None
    module: str | None
    start_line: int | None
    end_line: int | None


@dataclass(frozen=True)
class ProbeOutcome:
    """One Lean probe. `found` is True only when the kernel accepted a proof."""

    kind: str
    found: bool
    applicable: bool
    tactic: str | None
    axioms: tuple[str, ...]
    note: str

    @property
    def headline(self) -> str:
        if self.kind == "vacuity":
            if self.found:
                return (f"Red flag: Lean derived False from the hypotheses (with `{self.tactic}`). "
                        "They contradict each other, so the theorem says nothing.")
            return self.note
        if self.found:
            return (f"Red flag: Lean proved the conclusion without the hypotheses (with "
                    f"`{self.tactic}`). They aren't needed, or the conclusion is weaker than it "
                    "looks.")
        return self.note


@dataclass(frozen=True)
class StatementReport:
    theorem: str
    file: str
    kind: str
    statement: str
    binders: tuple[Binder, ...]
    conclusion: str
    definitions: tuple[ProjectDefinition, ...]
    axioms: tuple[str, ...]
    probes: tuple[ProbeOutcome, ...]
    receipt: Receipt
    reused_from: str | None = None  # when the result was stored: the time of that Lean run

    @property
    def proof_left_open(self) -> bool:
        """True for a statement whose proof is `sorry` (such as a comparator challenge)."""
        return "sorryAx" in self.axioms

    @property
    def red_flags(self) -> tuple[ProbeOutcome, ...]:
        return tuple(probe for probe in self.probes if probe.found)


def read_statement(
    workspace: LeanWorkspace, path: Path, theorem: str, *, probes: bool = True,
    timeout: float = TIMEOUT_SECONDS,
) -> StatementReport:
    """Ask Lean what `theorem` in `path` states, and optionally run the probes."""
    if not workspace.exporter.is_file():
        raise StatementError(f"Scry's exporter for {workspace.toolchain} isn't built. "
                             "Run `make lean-setup`.")
    stored = stored_result_path(workspace, path, theorem, probes=probes)
    if stored.is_file():
        record = json.loads(stored.read_text(encoding="utf-8"))
        saved = record["evidence"]
        evidence = LeanRunEvidence(**{**saved, "command": tuple(saved["command"])})
        report = report_from_json(record["report"], workspace.relative(path), evidence)
        return replace(report, reused_from=str(record["ran_at"]))
    workspace.build_imports(path)
    mode = "--statement-probes" if probes else "--statement"
    command = [str(workspace.lake), "env", str(workspace.exporter), mode, str(path.resolve()),
               theorem]
    started = time.monotonic()
    try:
        completed = subprocess.run(command, cwd=workspace.root, env=workspace.environment(),
                                   capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise StatementError(
            f"Lean took longer than {timeout:.0f} seconds and was stopped."
        ) from exc
    seconds = time.monotonic() - started
    if completed.returncode != 0:
        details = (completed.stderr.strip() or completed.stdout.strip())[-2000:]
        raise StatementError(f"Lean couldn't report on '{theorem}': {details}")
    lines = completed.stdout.strip().splitlines()
    try:
        data = json.loads(lines[-1]) if lines else None
    except json.JSONDecodeError as exc:
        raise StatementError("Lean's statement report was not valid JSON.") from exc
    if not isinstance(data, dict) or data.get("format") != STATEMENT_FORMAT:
        raise StatementError("Lean's output was not a statement report.")
    evidence = LeanRunEvidence(
        command=tuple(command), exit_code=completed.returncode, timed_out=False,
        output_sha256=hashlib.sha256(
            (completed.stdout + "\0" + completed.stderr).encode("utf-8")
        ).hexdigest(),
        seconds=seconds,
    )
    report = report_from_json(data, workspace.relative(path), evidence)
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_text(json.dumps({
        "ran_at": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "report": data,
        "evidence": {**evidence.to_dict(), "seconds": evidence.seconds},
    }), encoding="utf-8")
    return report


def stored_result_path(
    workspace: LeanWorkspace, path: Path, theorem: str, *, probes: bool
) -> Path:
    """Where a statement result is stored. It changes when anything that could change
    Lean's answer changes: the file's contents, the theorem, the Lean version, the exporter
    build, or whether probes ran."""
    key = fingerprint_data({
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "theorem": theorem,
        "toolchain": workspace.toolchain, "probes": probes,
        "exporter_sha256": hashlib.sha256(workspace.exporter.read_bytes()).hexdigest(),
    }).split(":")[1]
    return workspace.root / STORE_FOLDER / f"{key}.json"


def report_from_json(
    data: dict[str, Any], file: str, evidence: LeanRunEvidence
) -> StatementReport:
    probes = _probes(data.get("probes"))
    flags = [p for p in probes if p.found]
    if not probes:
        summary = "Lean read the statement (no probes were run)."
    elif flags:
        summary = "Lean found red flags: " + ", ".join(p.kind for p in flags) + "."
    else:
        summary = "Lean read the statement; the probes found no red flags (which proves nothing)."
    receipt = Receipt.from_lean_run(
        evidence,
        subject=f"statement of '{data['theorem']}' in {file}",
        subject_fingerprint=fingerprint_data({"statement": data["statement"],
                                              "file": file, "lean": data.get("lean_version")}),
        passed=not flags,
        summary=summary,
    )
    return StatementReport(
        theorem=str(data["theorem"]),
        file=file,
        kind=str(data["kind"]),
        statement=str(data["statement"]),
        binders=tuple(Binder(b["name"], b["type"], b["binder"], bool(b["is_prop"]))
                      for b in data["binders"]),
        conclusion=str(data["conclusion"]),
        definitions=tuple(_definition(d) for d in data["definitions"]),
        axioms=tuple(data["axioms"]),
        probes=probes,
        receipt=receipt,
    )


def _definition(d: dict[str, Any]) -> ProjectDefinition:
    start, end = d.get("start"), d.get("end")
    return ProjectDefinition(
        name=str(d["name"]), kind=str(d["kind"]), depth=int(d["depth"]), type=str(d["type"]),
        value=d.get("value"), module=d.get("module"),
        start_line=int(start["line"]) if start else None,
        end_line=int(end["line"]) if end else None,
    )


def _probes(raw: Any) -> tuple[ProbeOutcome, ...]:
    if not isinstance(raw, dict):
        return ()
    out: list[ProbeOutcome] = []
    for kind in ("vacuity", "triviality"):
        probe = raw.get(kind)
        if not isinstance(probe, dict):
            continue
        out.append(ProbeOutcome(
            kind=kind, found=bool(probe.get("found")),
            applicable=not probe.get("not_applicable", False),
            tactic=probe.get("tactic"), axioms=tuple(probe.get("axioms", ())),
            note=str(probe.get("note", "")),
        ))
    return tuple(out)
