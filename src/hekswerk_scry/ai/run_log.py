"""An append-only record of one audit, written while it runs, for people to follow.

Each line is one event, as JSON: what the run is about (`start`), what the model said
between tool calls (`model`), each tool result (`evidence`), each comparison row the helper
recorded (`verdict`), and how it ended (`finish` or `stopped`). Lines are only ever added,
and each is written in one piece and flushed at once, so a reader (the browser workbench)
can follow a run while it happens, and a crash or restart loses at most the event being
written. A reader ignores a last line that isn't complete JSON yet.

The log is for people. The AI helper never reads it.
"""

import json
import time
from pathlib import Path
from typing import Any

from hekswerk_scry.ai.tools import Evidence

LOG_FORMAT = "hekswerk-scry/audit-log"
LOG_VERSION = 1
LOG_SUFFIX = ".events.jsonl"


class RunLog:
    def __init__(self, path: Path) -> None:
        if not path.name.endswith(LOG_SUFFIX):
            raise ValueError(f"A run log's name must end in {LOG_SUFFIX}: {path.name}")
        if path.exists():
            raise ValueError(f"{path} already exists. A run log is never written over.")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.seq = 0

    def write(self, kind: str, **data: Any) -> None:
        self.seq += 1
        event = {"seq": self.seq, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "kind": kind, **data}
        line = json.dumps(event, ensure_ascii=False, default=str) + "\n"
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(line)
            stream.flush()

    def evidence(self, item: Evidence) -> None:
        self.write(
            "evidence", id=item.evidence_id, tool=item.tool, arguments=item.arguments,
            summary=item.summary, result=item.result,
            checked_by=item.checked_by.value if item.checked_by else None,
            checked_by_label=item.checked_by.label if item.checked_by else "lookup (no check)",
            receipt_id=item.receipt_id,
        )


def read_events(path: Path, after: int = 0) -> list[dict[str, Any]]:
    """The events after `after`, in order. A last line still being written is left out."""
    events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.endswith("\n"):
                break  # still being written
            event = json.loads(line)
            if not isinstance(event, dict) or not isinstance(event.get("seq"), int):
                raise ValueError(f"{path.name} has a line that isn't a run-log event.")
            if event["seq"] > after:
                events.append(event)
    return events
