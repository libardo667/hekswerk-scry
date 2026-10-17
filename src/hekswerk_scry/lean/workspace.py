"""Finding the Lean project a proof lives in, and the tools needed to run Lean there.

Two things are needed to work on a Lean proof:

- **The project**: the Lake project the proof file belongs to. Lean runs there, so the
  file's imports resolve. Scry's own project is the `lean/` folder of this repository
  (pinned to the Lean and Mathlib versions of the public AlphaProof release). Any other
  Lake project works too, such as a clone of `openai/math`'s `lean/` folder.
- **An exporter**: Scry's Lean program that records how a proof fits together. It reads
  Lean's internals, so it is built separately for each supported Lean version
  (`EXPORTERS` below). It imports only Lean itself, so one build serves every project on
  that version.

Set SCRY_LEAN_WORKSPACE to use a different folder as Scry's own project, and SCRY_LAKE
to use a specific `lake` program.
"""

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from hekswerk_scry.lean.processes import run_program

REPOSITORY = Path(__file__).resolve().parents[3]

# Lean version -> the folder (relative to the repository) whose Lake project builds the
# exporter for that version.
EXPORTERS = {
    "leanprover/lean4:v4.10.0-rc2": "lean",
    "leanprover/lean4:v4.34.1": "lean-exporters/v4.34.1",
}

_IMPORT = re.compile(r"^\s*(?:public\s+)?(?:meta\s+)?import\s+(?:all\s+)?([\w.]+)")
BUILD_TIMEOUT_SECONDS = 3600


class LeanSetupError(RuntimeError):
    """Lean, Lake, or a project can't be found or used. The message says how to fix it."""


SETUP_HINT = (
    "See 'Setting up Lean' in README.md: install elan, then run `make lean-setup` from the "
    "repository root."
)


@dataclass(frozen=True)
class LeanWorkspace:
    """A Lake project to run Lean in, and the exporter for its Lean version."""

    root: Path
    lake: Path
    exporter: Path
    is_scry_project: bool = True

    @property
    def toolchain(self) -> str:
        return (self.root / "lean-toolchain").read_text(encoding="utf-8").strip()

    @property
    def mathlib_revision(self) -> str | None:
        """The exact Mathlib commit the project uses, from its lock file."""
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
        keep = ("HOME", "ELAN_HOME", "LANG", "LC_ALL", "TMPDIR", "GLIBC_TUNABLES")
        env = {key: os.environ[key] for key in keep if key in os.environ}
        env["PATH"] = os.pathsep.join([str(self.lake.parent), "/usr/local/bin", "/usr/bin", "/bin"])
        return env

    def relative(self, path: Path) -> str:
        """`path` as Scry records it: relative to the project when it is inside it."""
        resolved = path.resolve()
        try:
            return resolved.relative_to(self.root).as_posix()
        except ValueError:
            return str(resolved)

    def resolve(self, recorded: str) -> Path:
        """The inverse of `relative`."""
        path = Path(recorded)
        return path if path.is_absolute() else self.root / path

    def project_imports(self, path: Path) -> list[str]:
        """The modules `path` imports that belong to this project (not to its packages)."""
        modules: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            found = _IMPORT.match(line)
            if found and (self.root / (found.group(1).replace(".", "/") + ".lean")).is_file():
                modules.append(found.group(1))
        return modules

    def build_imports(self, path: Path, *, timeout: float = BUILD_TIMEOUT_SECONDS) -> None:
        """Build the project's own modules that `path` imports, so Lean can load them.

        Mathlib and other packages come prebuilt (`lake exe cache get`); a project's own
        files may not be, and building them can take a while the first time.
        """
        modules = self.project_imports(path)
        if not modules:
            return
        # `lake build` takes half a minute even when nothing needs building, so remember
        # what was built and skip it while none of the project's sources have changed.
        record = self.root / ".scry-runs" / "built-imports.json"
        key, stamp = " ".join(sorted(modules)), self.sources_stamp()
        try:
            built = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            built = {}
        if not isinstance(built, dict):
            built = {}
        if built.get(key) == stamp:
            return
        completed = run_program([str(self.lake), "build", *modules], cwd=self.root,
                                env=self.environment(), timeout=timeout)
        if completed.timed_out:
            raise LeanSetupError(
                f"Building the files {path.name} imports took longer than {timeout:.0f} seconds."
            )
        if completed.exit_code != 0:
            tail = (completed.stdout + completed.stderr).strip()[-1500:]
            raise LeanSetupError(f"Couldn't build the files {path.name} imports: {tail}")
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({**built, key: stamp}), encoding="utf-8")

    def sources_stamp(self) -> str:
        """Changes whenever any of the project's own Lean files, or its package setup, does.

        Every `.lean` file outside `.lake` (packages and build output) and `.scry-runs`
        (Scry's scratch files, which nothing imports) counts, so an edit anywhere in the
        project means building again.
        """
        digest = hashlib.sha256()
        for name in ("lakefile.lean", "lakefile.toml", "lake-manifest.json", "lean-toolchain"):
            digest.update(f"{name}:{_stat_key(self.root / name)}\n".encode())
        for folder, subfolders, files in os.walk(self.root):
            subfolders[:] = sorted(s for s in subfolders if s not in {".lake", ".scry-runs"})
            for name in sorted(files):
                if name.endswith(".lean"):
                    path = Path(folder) / name
                    digest.update(f"{path.relative_to(self.root)}:{_stat_key(path)}\n".encode())
        return digest.hexdigest()


def _stat_key(path: Path) -> str:
    try:
        info = path.stat()
    except OSError:
        return "missing"
    return f"{info.st_mtime_ns}:{info.st_size}"


def find_workspace(start: Path | None = None) -> LeanWorkspace:
    """Scry's own project (the `lean/` folder of this repository)."""
    root = _find_scry_root(start or Path.cwd())
    return LeanWorkspace(
        root=root, lake=_find_lake(), exporter=root / ".lake" / "build" / "bin" / "scry-export"
    )


def workspace_for_file(path: Path) -> LeanWorkspace:
    """The Lake project `path` belongs to, with the exporter for its Lean version."""
    resolved = path.resolve()
    for folder in resolved.parents:
        if (folder / "lean-toolchain").is_file() and (
            (folder / "lakefile.lean").is_file() or (folder / "lakefile.toml").is_file()
        ):
            return workspace_for_project(folder)
    raise LeanSetupError(
        f"'{path}' is not inside a Lake project (no folder above it has a lean-toolchain "
        "and a lakefile)."
    )


def workspace_for_project(root: Path) -> LeanWorkspace:
    root = root.resolve()
    toolchain = (root / "lean-toolchain").read_text(encoding="utf-8").strip()
    exporter_dir = EXPORTERS.get(toolchain)
    if exporter_dir is None:
        raise LeanSetupError(
            f"The project at '{root}' uses {toolchain}, which Scry doesn't support yet. "
            f"Supported Lean versions: {', '.join(EXPORTERS)}."
        )
    exporter = REPOSITORY / exporter_dir / ".lake" / "build" / "bin" / "scry-export"
    if not exporter.is_file():
        raise LeanSetupError(
            f"Scry's exporter for {toolchain} isn't built yet (expected {exporter}). " + SETUP_HINT
        )
    scry_root = REPOSITORY / "lean"
    return LeanWorkspace(
        root=root, lake=_find_lake(), exporter=exporter,
        is_scry_project=root == scry_root.resolve(),
    )


def workspace_for_map(source_project: str | None, start: Path | None = None) -> LeanWorkspace:
    """The project a map's Lean file belongs to (None means Scry's own project)."""
    if source_project is None:
        return find_workspace(start)
    root = Path(source_project)
    if not (root / "lean-toolchain").is_file():
        raise LeanSetupError(
            f"The map's Lean project '{root}' isn't there any more (no lean-toolchain found)."
        )
    return workspace_for_project(root)


def _find_scry_root(start: Path) -> Path:
    configured = os.environ.get("SCRY_LEAN_WORKSPACE")
    if configured:
        root = Path(configured).resolve()
        if not (root / "lakefile.lean").is_file():
            raise LeanSetupError(
                f"SCRY_LEAN_WORKSPACE points to '{root}', which has no lakefile.lean."
            )
        return root
    here = start.resolve()
    for folder in (here, *here.parents, REPOSITORY):
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
