"""OpenAI's mathematics repository (github.com/openai/math, Apache-2.0).

The repository's `lean/` folder is a Lake project (Lean v4.34.1) holding formalizations
of some of its papers. For each formalized result there is a *comparator challenge*: a
short Lean file that states the result (with `sorry` for the proof), plus a JSON file
naming the module whose theorem proves it. OpenAI's `lean/docs/` folder has a scope note
per paper, saying what the formalization covers and leaves out.

Scry clones only what it needs: the `lean/` folder, and the LaTeX source of a paper when
a statement is lined up against it. Set SCRY_OPENAI_MATH to use an existing clone.

The scope notes are kept apart from everything the AI helper can read: they are the
answer key for judging how well statement checking works.
"""

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from hekswerk_scry.lean.workspace import REPOSITORY

CLONE_URL = "https://github.com/openai/math.git"
DEFAULT_FOLDER = REPOSITORY / "lean-projects" / "openai-math"
_PAPER_LINK = re.compile(r"\(\.\./\.\./preprints/([^/)]+)/paper\.pdf\)")


class OpenAIMathError(RuntimeError):
    """The repository isn't there or doesn't look as expected. The message says why."""


def root() -> Path:
    configured = os.environ.get("SCRY_OPENAI_MATH")
    return Path(configured).resolve() if configured else DEFAULT_FOLDER


def lean_project() -> Path:
    project = root() / "lean"
    if not (project / "lean-toolchain").is_file():
        raise OpenAIMathError(
            f"No clone of openai/math at '{root()}'. Run `scry fetch-openai-math`, or set "
            "SCRY_OPENAI_MATH to an existing clone."
        )
    return project


def fetch(*, timeout: float = 1800) -> Path:
    """Clone the repository's `lean/` folder (no papers yet), or confirm it is there."""
    target = root()
    if (target / "lean" / "lean-toolchain").is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    for command in (
        ["git", "clone", "--filter=blob:none", "--sparse", "--depth", "1", CLONE_URL, str(target)],
        ["git", "-C", str(target), "sparse-checkout", "set", "lean"],
    ):
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                                   check=False)
        if completed.returncode != 0:
            raise OpenAIMathError(f"`{' '.join(command[:3])}` failed: {completed.stderr.strip()}")
    return target


@dataclass(frozen=True)
class Challenge:
    """One comparator challenge: a formal statement and the module that proves it."""

    name: str
    statement_file: Path
    solution_module: str
    solution_file: Path
    theorem_names: tuple[str, ...]
    permitted_axioms: tuple[str, ...]

    @property
    def is_supporting_result(self) -> bool:
        return self.name.endswith("Support")


def challenges() -> list[Challenge]:
    folder = lean_project() / "ComparatorChallenges"
    return [_challenge(spec) for spec in sorted(folder.glob("*.json"))]


def challenge(name: str) -> Challenge:
    spec = lean_project() / "ComparatorChallenges" / f"{name}.json"
    if not spec.is_file():
        raise OpenAIMathError(
            f"There is no comparator challenge called '{name}'. "
            "`scry openai-challenges` lists them."
        )
    return _challenge(spec)


def _challenge(spec: Path) -> Challenge:
    data = json.loads(spec.read_text(encoding="utf-8"))
    project = lean_project()
    solution = str(data["solution_module"])
    return Challenge(
        name=spec.stem,
        statement_file=project / "ComparatorChallenges" / f"{spec.stem}.lean",
        solution_module=solution,
        solution_file=project / (solution.replace(".", "/") + ".lean"),
        theorem_names=tuple(data["theorem_names"]),
        permitted_axioms=tuple(data.get("permitted_axioms", ())),
    )


# --- Scope notes: the answer key. Never handed to the AI helper. ---------------------


def scope_note(item: Challenge) -> Path | None:
    """OpenAI's scope note that links to this challenge, if there is one."""
    link = f"ComparatorChallenges/{item.name}.lean"
    for note in sorted((lean_project() / "docs").glob("*.md")):
        if link in note.read_text(encoding="utf-8"):
            return note
    return None


def papers_of(note: Path) -> tuple[str, ...]:
    """The paper folders (under `preprints/`) a scope note is about."""
    return tuple(dict.fromkeys(_PAPER_LINK.findall(note.read_text(encoding="utf-8"))))


# --- Paper sources -------------------------------------------------------------------


def paper_source(paper: str, *, timeout: float = 600) -> list[Path]:
    """The LaTeX files of one paper, fetched on first use. Returns them in a stable order."""
    folder = root() / "preprints" / paper / "build"
    if not folder.is_dir():
        completed = subprocess.run(
            ["git", "-C", str(root()), "sparse-checkout", "add", f"preprints/{paper}/build"],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        if completed.returncode != 0 or not folder.is_dir():
            raise OpenAIMathError(
                f"Couldn't fetch the LaTeX source of '{paper}': {completed.stderr.strip()}"
            )
    files = sorted(folder.rglob("*.tex"), key=lambda p: (p.name != "main.tex", str(p)))
    if not files:
        raise OpenAIMathError(f"The paper '{paper}' has no LaTeX source in the repository.")
    return files
