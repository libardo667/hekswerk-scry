"""Finding Scry's Lean workspace and the tools needed to run it.

The workspace is the `lean/` folder of this repository: a Lake project pinned to the same
Lean and Mathlib versions as the public AlphaProof release. Set SCRY_LEAN_WORKSPACE to use
a different folder, and SCRY_LAKE to use a specific `lake` program.
"""

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


class LeanSetupError(RuntimeError):
    """Lean, Lake, or the workspace can't be found. The message says how to fix it."""


SETUP_HINT = (
    "See 'Setting up Lean' in README.md: install elan, then run `make lean-setup` from the "
    "repository root."
)


@dataclass(frozen=True)
class LeanWorkspace:
    """A Lake project Scry can run Lean in."""

    root: Path
    lake: Path

    @property
    def toolchain(self) -> str:
        return (self.root / "lean-toolchain").read_text(encoding="utf-8").strip()

    @property
    def mathlib_revision(self) -> str | None:
        """The exact Mathlib commit the workspace uses, from its lock file."""
        manifest = self.root / "lake-manifest.json"
        if not manifest.is_file():
            return None
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for package in data.get("packages", []):
            if package.get("name") == "mathlib":
                revision = package.get("rev")
                return str(revision) if revision else None
        return None

    def environment(self) -> dict[str, str]:
        """A small, predictable environment for running Lean (no inherited secrets)."""
        keep = ("HOME", "ELAN_HOME", "LANG", "LC_ALL", "TMPDIR")
        env = {key: os.environ[key] for key in keep if key in os.environ}
        env["PATH"] = os.pathsep.join([str(self.lake.parent), "/usr/local/bin", "/usr/bin", "/bin"])
        return env

    def relative(self, path: Path) -> str:
        """`path` as Scry records it: relative to the workspace when it is inside it."""
        resolved = path.resolve()
        try:
            return resolved.relative_to(self.root).as_posix()
        except ValueError:
            return str(resolved)

    def resolve(self, recorded: str) -> Path:
        """The inverse of `relative`."""
        path = Path(recorded)
        return path if path.is_absolute() else self.root / path


def find_workspace(start: Path | None = None) -> LeanWorkspace:
    """Find the workspace and `lake`, or explain what is missing."""
    root = _find_root(start or Path.cwd())
    lake = _find_lake()
    return LeanWorkspace(root=root, lake=lake)


def _find_root(start: Path) -> Path:
    configured = os.environ.get("SCRY_LEAN_WORKSPACE")
    if configured:
        root = Path(configured).resolve()
        if not (root / "lakefile.lean").is_file():
            raise LeanSetupError(
                f"SCRY_LEAN_WORKSPACE points to '{root}', which has no lakefile.lean."
            )
        return root
    here = start.resolve()
    for folder in (here, *here.parents):
        candidate = folder / "lean"
        if (candidate / "lakefile.lean").is_file() and (candidate / "ScryExport").is_dir():
            return candidate
        if (folder / "lakefile.lean").is_file() and (folder / "ScryExport").is_dir():
            return folder
    raise LeanSetupError(
        "Couldn't find Scry's Lean workspace (the 'lean' folder of the repository). Run Scry "
        "from inside the repository, or set SCRY_LEAN_WORKSPACE. " + SETUP_HINT
    )


def _find_lake() -> Path:
    configured = os.environ.get("SCRY_LAKE")
    candidates: list[str | None] = [configured] if configured else []
    candidates += [shutil.which("lake"), str(Path.home() / ".elan" / "bin" / "lake")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise LeanSetupError("Couldn't find the `lake` program that comes with Lean. " + SETUP_HINT)
