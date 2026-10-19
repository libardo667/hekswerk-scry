"""Making an outline of a result (see `models/outline.py`) with Lean.

Lean elaborates the file the result is in, then the exporter (`--outline`, in
`ScryExport/Outline.lean`) walks Lean's record of the finished declarations: the result,
the project declarations its statement and proof use, theirs, and so on. Scry adds the text
of each part, read from the file Lean says it is written in, and each file's fingerprint, so
an outline whose files have since changed can be recognised.

Loading the project takes minutes (Mathlib, then the project itself); walking it takes
seconds.
"""

import hashlib
from pathlib import Path
from typing import Any

from hekswerk_scry.lean.statement import run_exporter
from hekswerk_scry.lean.workspace import LeanWorkspace
from hekswerk_scry.models.outline import Outline, OutlinePart, UnusedHypothesis

EXPORTER_FORMAT = "hekswerk-scry/lean-outline"
TIMEOUT_SECONDS = 3600


class OutlineMakingError(RuntimeError):
    """Lean couldn't outline the result. The message says why."""


def make_outline(workspace: LeanWorkspace, path: Path, theorem: str, *,
                 timeout: float = TIMEOUT_SECONDS) -> Outline:
    if not workspace.exporter.is_file():
        raise OutlineMakingError(f"Scry's exporter for {workspace.toolchain} isn't built. "
                                 "Run `make lean-setup`.")
    workspace.build_imports(path)
    data, _ = run_exporter(workspace, "outline", path, theorem, timeout, EXPORTER_FORMAT,
                           OutlineMakingError)
    return outline_from_lean(data, workspace, path)


def outline_from_lean(data: dict[str, Any], workspace: LeanWorkspace, path: Path) -> Outline:
    """Turn the exporter's report into an outline, adding each part's text from its file."""
    texts: dict[str, list[str]] = {}
    hashes: dict[str, str] = {}

    def file_of(module: str | None) -> str | None:
        found = path.resolve() if module is None else _module_file(workspace.root, module)
        if found is None:
            return None
        name = workspace.relative(found)
        if name not in texts:
            raw = found.read_bytes()
            hashes[name] = hashlib.sha256(raw).hexdigest()
            texts[name] = raw.decode("utf-8").splitlines()
        return name

    parts: dict[str, OutlinePart] = {}
    for raw in data["parts"]:
        module = raw["module"]
        file = file_of(module)
        start = raw["start"]["line"] if raw["start"] else None
        end = raw["end"]["line"] if raw["end"] else None
        source = None
        if file is not None and start is not None and end is not None:
            start, source = _without_doc_comment(texts[file], start, end)
        part = OutlinePart(
            part_id=raw["id"], name=raw["name"], kind=raw["kind"], private=raw["private"],
            module=module, file=file, start_line=start, end_line=end,
            doc=raw["doc"].strip() if raw["doc"] else None,
            statement=raw["statement"], source=source,
            statement_uses=tuple(raw["statement_uses"]), body_uses=tuple(raw["body_uses"]),
            unused_hypotheses=tuple(UnusedHypothesis(h["name"], h["statement"])
                                    for h in raw["unused_hypotheses"]),
        )
        parts[part.part_id] = part
    return Outline(result=data["result"], project=str(workspace.root),
                   lean_version=data["lean_version"], file_sha256=hashes,
                   axioms=tuple(data["axioms"]), parts=parts)


def _without_doc_comment(lines: list[str], start: int, end: int) -> tuple[int, str]:
    """A declaration's text and first line, without its doc comment.

    Lean v4.34 counts a doc comment as part of where a declaration is written and v4.10
    doesn't; the doc string is kept separately anyway, so the text starts after it."""
    text = "\n".join(lines[start - 1:end])
    if not text.lstrip().startswith("/--"):
        return start, text
    close = text.find("-/", text.index("/--") + 3)
    if close == -1:
        return start, text
    start += text.count("\n", 0, close)
    rest = text[close + 2:]
    if rest.split("\n", 1)[0].strip():  # the declaration goes on on the same line
        return start, rest.lstrip(" ")
    return start + 1, rest.split("\n", 1)[1] if "\n" in rest else ""


def _module_file(project: Path, module: str) -> Path | None:
    """The file a module is compiled from: in the project, or in one of the packages it
    depends on (`.lake/packages/*`)."""
    relative = Path(*module.split(".")).with_suffix(".lean")
    for root in [project, *sorted((project / ".lake" / "packages").glob("*"))]:
        if (root / relative).is_file():
            return root / relative
    return None


def changed_files(outline: Outline) -> list[str]:
    """The files of an outline that are no longer as they were when it was made (or are
    gone). Empty when the project folder isn't on this machine, since then nothing can be
    compared."""
    project = Path(outline.project)
    if not project.is_dir():
        return []
    changed = []
    for name, digest in outline.file_sha256.items():
        file = Path(name) if Path(name).is_absolute() else project / name
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            changed.append(name)
    return changed
