"""A Lean process kept running, so a check doesn't reload a file's imports every time.

Loading a file's imports (often all of Mathlib) is most of what a fresh `lean` run costs:
a minute or two, against a fraction of a second for the proof itself. Scry's exporter has
a mode, `scry-export --serve`, that stays running and keeps the environment after loading
a file's imports. A later file with exactly the same import lines starts from it. Each file
still starts from the environment right after its imports, so nothing one check declares,
and no option it sets, is visible to the next (`lean/ScryExport/Load.lean`).

One process holds one set of imports: loading a second set into the same process breaks
Lean v4.34.1's environment. So Scry keeps a few processes, one per set of import lines, and
Lean itself refuses a file whose imports differ from what its process loaded. Scry then
restarts that process with the file's own imports.

A `check` reply holds Lean's messages exactly as `lean --json` prints them, and the runner
judges them with the same code as a fresh run. A test runs a set of files both ways and
requires identical results (`lean_tests/test_lean_worker.py`).

The process is restarted whenever what it loaded could be out of date: when the exporter
is rebuilt, or when any of the project's own build output or its package list changes. It
is also restarted after a check runs out of time.

Set SCRY_LEAN_WORKER=off to run a fresh `lean` for every check instead.

Lean files are programs, and here they all run in one process. Only check files you trust.
"""

import atexit
import contextlib
import json
import os
import selectors
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from hekswerk_scry.lean.processes import stop_group
from hekswerk_scry.lean.workspace import LeanWorkspace

REPLY_PREFIX = "scry-reply "
# The exact text `scry-export` refuses a file with (ScryLoad.otherImports).
OTHER_IMPORTS = "scry: this Lean process has other imports loaded"
# Each process can hold all of Mathlib (about 5 GB of memory), so only a few are kept.
MAX_PROCESSES = 2
SWITCH = "SCRY_LEAN_WORKER"
LOG_NAME = "lean-worker.log"


class LeanWorkerError(RuntimeError):
    """The kept-running Lean process failed, as opposed to Lean rejecting a proof."""


@dataclass(frozen=True)
class WorkerReply:
    """One answer from the kept-running Lean process."""

    command: tuple[str, ...]
    result: dict[str, Any] | None
    printed: tuple[str, ...]  # lines the file itself printed while Lean elaborated it
    raw: str  # the reply exactly as received, for the receipt's output fingerprint
    seconds: float
    timed_out: bool


def enabled() -> bool:
    return os.environ.get(SWITCH, "on").strip().lower() not in {"off", "0", "no", "false"}


class LeanWorker:
    """One `scry-export --serve` process for one Lake project and one exporter build."""

    def __init__(self, workspace: LeanWorkspace) -> None:
        self.workspace = workspace
        self.command = (str(workspace.lake), "env", str(workspace.exporter), "--serve")
        self._process: subprocess.Popen[bytes] | None = None
        self._stamp: tuple[Any, ...] = ()
        self._buffer = b""
        self._next_id = 0

    # --- the process ---------------------------------------------------------------

    def _current_stamp(self) -> tuple[Any, ...]:
        """Changes whenever the loaded environment could be out of date."""
        root = self.workspace.root
        build = root / ".lake" / "build" / "lib"
        newest = max((p.stat().st_mtime_ns for p in _files(build, ".olean")), default=0)
        return (_stat(self.workspace.exporter), _stat(root / "lake-manifest.json"), newest)

    def _start(self) -> subprocess.Popen[bytes]:
        log_folder = self.workspace.root / ".scry-runs"
        log_folder.mkdir(parents=True, exist_ok=True)
        with (log_folder / LOG_NAME).open("ab") as log:
            process = subprocess.Popen(
                self.command, cwd=self.workspace.root, env=self.workspace.environment(),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, bufsize=0,
                # Its own process group, so stopping it also stops the Lean program that
                # `lake env` starts underneath it.
                start_new_session=True,
            )
        self._buffer = b""
        return process

    def close(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            stop_group(process)
        _close_pipes(process)

    def _kill(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            stop_group(process)
            _close_pipes(process)

    # --- requests ------------------------------------------------------------------

    def ask(self, mode: str, path: Path, theorem: str, *, timeout: float) -> WorkerReply:
        """Send one request and wait for its reply. A timeout stops the process.

        If Lean refuses the file because this process loaded other imports, the process is
        restarted with the file's own imports. A new process has nothing loaded, so it
        can't refuse again.
        """
        try:
            return self._ask_once(mode, path, theorem, timeout=timeout)
        except _OtherImportsError:
            self.close()
        try:
            return self._ask_once(mode, path, theorem, timeout=timeout)
        except _OtherImportsError as exc:
            raise LeanWorkerError("Scry bug: a new Lean process refused a file's imports.") from exc

    def _ask_once(self, mode: str, path: Path, theorem: str, *, timeout: float) -> WorkerReply:
        stamp = self._current_stamp()
        if self._process is not None and (stamp != self._stamp or self._process.poll() is not None):
            self.close()
        if self._process is None:
            self._process = self._start()
            self._stamp = stamp
        process = self._process
        assert process.stdin is not None and process.stdout is not None
        self._next_id += 1
        request_id = self._next_id
        request = {"id": request_id, "mode": mode, "file": str(path.resolve()), "theorem": theorem}
        command = (*self.command, mode, str(path.resolve()), theorem)
        started = time.monotonic()
        try:
            process.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
            process.stdin.flush()
        except OSError as exc:
            self._kill()
            raise LeanWorkerError(
                f"Couldn't send the request to Lean: {exc}. {self._log_tail()}"
            ) from exc
        stray: list[str] = []
        while True:
            line = self._read_line(process.stdout, started + timeout)
            if line is None:
                self._kill()
                return WorkerReply(command, None, tuple(stray), "", time.monotonic() - started,
                                   timed_out=True)
            if line == "":
                self._kill()
                raise LeanWorkerError(f"The kept-running Lean process stopped. {self._log_tail()}")
            if not line.startswith(REPLY_PREFIX):
                stray.append(line)
                continue
            reply = json.loads(line[len(REPLY_PREFIX):])
            if reply.get("id") != request_id:
                self._kill()
                raise LeanWorkerError("Scry bug: Lean answered a different request.")
            break
        seconds = time.monotonic() - started
        printed = (*stray, *str(reply.get("printed", "")).splitlines())
        if reply.get("error") == OTHER_IMPORTS:
            raise _OtherImportsError
        if "error" in reply:
            raise LeanWorkerError(f"Lean couldn't process the file: {reply['error']}")
        result = reply.get("result")
        if not isinstance(result, dict):
            raise LeanWorkerError("Scry bug: Lean's reply had no result.")
        return WorkerReply(command, result, printed, line, seconds, timed_out=False)

    def _read_line(self, stream: IO[bytes], deadline: float) -> str | None:
        """The next line, "" at end of output, or None if the deadline passes first."""
        with selectors.DefaultSelector() as selector:
            selector.register(stream, selectors.EVENT_READ)
            while b"\n" not in self._buffer:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    return None
                chunk = os.read(stream.fileno(), 1 << 16)
                if not chunk:
                    return ""
                self._buffer += chunk
        line, self._buffer = self._buffer.split(b"\n", 1)
        return line.decode("utf-8", errors="replace")

    def _log_tail(self) -> str:
        log = self.workspace.root / ".scry-runs" / LOG_NAME
        try:
            tail = log.read_text(encoding="utf-8", errors="replace").strip()[-1500:]
        except OSError:
            return ""
        return f"Its last output: {tail}" if tail else ""


class _OtherImportsError(Exception):
    """Lean refused the file: its process has other imports loaded."""


_workers: dict[tuple[Path, Path, tuple[str, ...]], LeanWorker] = {}


def import_lines(path: Path) -> tuple[str, ...]:
    """The file's import lines, which decide which process it goes to. Lean makes the final
    call on whether two files' imports match; this only picks the likely process."""
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "prelude")):
            lines.append(" ".join(stripped.split()))
        elif stripped and not stripped.startswith("--"):
            break
    return tuple(lines)


def worker_for(workspace: LeanWorkspace, path: Path) -> LeanWorker | None:
    """The kept-running Lean for this project, exporter and set of imports, or None if
    switched off. Keeps at most MAX_PROCESSES running, stopping the least recently used."""
    if not enabled() or not workspace.exporter.is_file():
        return None
    key = (workspace.root.resolve(), workspace.exporter.resolve(), import_lines(path))
    worker = _workers.pop(key, None) or LeanWorker(workspace)
    _workers[key] = worker  # now the most recently used
    while len(_workers) > MAX_PROCESSES:
        _workers.pop(next(iter(_workers))).close()
    return worker


def close_all() -> None:
    for worker in _workers.values():
        worker.close()
    _workers.clear()


atexit.register(close_all)


def _close_pipes(process: subprocess.Popen[bytes]) -> None:
    for pipe in (process.stdin, process.stdout):
        if pipe is not None:
            with contextlib.suppress(OSError):
                pipe.close()


def _stat(path: Path) -> tuple[int, int] | None:
    try:
        info = path.stat()
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size)


def _files(folder: Path, suffix: str) -> Iterator[Path]:
    if folder.is_dir():
        yield from folder.rglob(f"*{suffix}")
