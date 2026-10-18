"""Shared by tests that check a process was stopped."""

import os
import time
from pathlib import Path


def alive(pid: int) -> bool:
    """Whether a process is still running, waiting up to five seconds for it to stop.

    A process can finish between any two of these steps, so every way of finding it gone
    (no such process, no `/proc` entry, or a read of it failing) counts as gone. A process
    that has stopped but whose exit status nobody has collected yet ("Z") counts as gone too.
    """
    for _ in range(50):
        try:
            os.kill(pid, 0)
            if Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z":
                return False
        except OSError:
            return False
        time.sleep(0.1)
    return True
