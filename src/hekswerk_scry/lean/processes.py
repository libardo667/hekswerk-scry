"""Running an outside program (Lean, Lake, git) so that stopping it really stops it.

`lake env lean ...` doesn't run Lean itself: it starts Lean as a child process. Stopping
only `lake` when time runs out leaves Lean running, possibly forever, holding a CPU and
gigabytes of memory. So every program Scry runs gets its own process group, and on a
timeout the whole group is stopped.
"""

import contextlib
import os
import signal
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finished:
    stdout: str
    stderr: str
    exit_code: int | None  # None when it ran out of time
    timed_out: bool


def run_program(
    command: Sequence[str],
    *,
    timeout: float,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> Finished:
    """Run `command` to the end, or stop it and everything it started after `timeout`."""
    process = subprocess.Popen(
        list(command), cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        stop_group(process)
        stdout, stderr = process.communicate()
        return Finished(stdout or "", stderr or "", None, timed_out=True)
    except BaseException:
        stop_group(process)  # interrupted: don't leave it running
        raise
    return Finished(stdout, stderr, process.returncode, timed_out=False)


def stop_group(process: "subprocess.Popen[str] | subprocess.Popen[bytes]") -> None:
    """Stop a process started in its own group, and everything it started."""
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()
