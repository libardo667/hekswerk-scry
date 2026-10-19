"""The browser workbench's server: a read-only window onto what Scry has done.

`scry serve` shows audits as they run (from their run logs), benchmark results, audit
reports, outlines and proof maps. It changes nothing and starts nothing: no Lean runs, no model
calls, no file writes. Starting work from the browser can come later.

Safety:
- It listens on 127.0.0.1 only, and refuses requests whose Host header names anything but
  this machine, so a web page elsewhere can't reach it through a DNS trick. The one
  exception, when it is set up, is a public name carried here by a Cloudflare Tunnel; those
  requests are answered only with a valid Cloudflare Access sign-in (see `access.py`),
  except the introduction: a fixed page about Scry (`public/`), with nothing from a run, a
  proof or a paper in it. The workbench itself is under /workbench/.
- Every file it serves is named by a token, "<source>:<path inside it>", that must resolve
  to a file of the expected kind inside one of the folders it was given. Anything else is
  refused, with a plain message.

Standard library only, like the rest of Scry's runtime.
"""

import json
import mimetypes
import re
import threading
from collections import deque
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from hekswerk_scry.ai.benchmark import (
    SCORE_MEANINGS,
    BenchmarkError,
    read_results,
    saved_rows,
    score_plant,
)
from hekswerk_scry.ai.run_log import LOG_FORMAT, LOG_SUFFIX, read_events
from hekswerk_scry.checker import check_wiring, scan_proof_map
from hekswerk_scry.files import (
    FORMAT_NAME,
    OUTLINE_SUFFIX,
    outline_from_dict,
    proof_map_from_dict,
    proof_map_to_dict,
)
from hekswerk_scry.lean.outline import changed_files
from hekswerk_scry.models.outline import MEANING_KINDS, Outline
from hekswerk_scry.web.access import TOKEN_HEADER, PublicAccess
from hekswerk_scry.web.blocks import foldable_blocks

STATIC = Path(__file__).parent / "static"
PUBLIC = Path(__file__).parent / "public"
WORKBENCH = "/workbench/"
RESULTS_FILE = "results.json"
SUMMARY_FILE = "summary.md"
_HOST = re.compile(r"^(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$")
_PUBLIC_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*\.(html|css|svg)$")
# The introduction runs no scripts and loads nothing but its own files.
_PUBLIC_POLICY = ("default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; "
                  "form-action 'none'; frame-ancestors 'none'")
_WORKBENCH_POLICY = ("default-src 'self'; style-src 'self'; script-src 'self'; "
                     "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")


class NotAllowedError(ValueError):
    """A request for something the workbench won't show. The message says why."""


def public_file(path: str) -> Path | None:
    """The introduction's file at this address, or None. These are the only files the public
    name serves without a sign-in: `/` is the introduction, and each other file sits directly
    under `/` by its plain name."""
    if not path.startswith("/"):
        return None
    name = "index.html" if path == "/" else path[1:]
    if not _PUBLIC_NAME.match(name):
        return None
    file = PUBLIC / name
    return file if file.is_file() else None


@dataclass(frozen=True)
class Source:
    """A folder the workbench may read: audit runs, or proof maps."""

    kind: str  # "runs" or "maps" (proof maps and outlines)
    root: Path


class Library:
    def __init__(self, sources: list[Source]) -> None:
        self.sources = [Source(s.kind, s.root.resolve()) for s in sources]
        # Outlines are large and slow to work through, so each is read once per version
        # of its file (path, size and modification time).
        self._outlines: dict[Path, tuple[tuple[int, int], Outline, dict[str, Any]]] = {}
        self._outlines_lock = threading.Lock()

    # --- tokens --------------------------------------------------------------------

    def token(self, path: Path) -> str:
        resolved = path.resolve()
        for index, source in enumerate(self.sources):
            if resolved.is_relative_to(source.root):
                return f"{index}:{resolved.relative_to(source.root).as_posix()}"
        raise NotAllowedError(f"{path} isn't inside any folder the workbench was given.")

    def resolve(self, token: str, *, suffixes: tuple[str, ...]) -> Path:
        index_text, sep, relative = token.partition(":")
        if not sep or not index_text.isdigit() or int(index_text) >= len(self.sources):
            raise NotAllowedError(f"'{token}' isn't a file the workbench knows about.")
        root = self.sources[int(index_text)].root
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise NotAllowedError(f"'{token}' isn't a file the workbench knows about.")
        if not path.name.endswith(suffixes):
            raise NotAllowedError(f"'{token}' isn't the kind of file this asks for.")
        return path

    # --- what there is ---------------------------------------------------------------

    def overview(self) -> dict[str, Any]:
        runs: list[dict[str, Any]] = []
        maps: list[dict[str, Any]] = []
        outlines: list[dict[str, Any]] = []
        for source in self.sources:
            if not source.root.is_dir():
                continue
            if source.kind == "runs":
                folders = {p.parent for p in source.root.rglob(f"*{LOG_SUFFIX}")}
                folders |= {p.parent for p in source.root.rglob(RESULTS_FILE)}
                folders |= {p.parent for p in source.root.rglob("*.md")}
                runs += [self._folder(folder) for folder in sorted(folders)]
            else:
                for path in sorted(source.root.rglob("*.json")):
                    entry = self._map(path)
                    if entry is not None:
                        (outlines if entry["kind"] == "outline" else maps).append(entry)
        runs.sort(key=lambda r: r["updated"], reverse=True)
        return {"runs": runs, "maps": maps, "outlines": outlines}

    def _folder(self, folder: Path) -> dict[str, Any]:
        logs = sorted(folder.glob(f"*{LOG_SUFFIX}"))
        logged = {p.name[: -len(LOG_SUFFIX)].rsplit("-", 2)[0] for p in logs}
        audits = [self._log_entry(p) for p in logs]
        for report in sorted(folder.glob("*.md")):
            if report.name != SUMMARY_FILE and report.stem not in logged:
                audits.append({"token": self.token(report), "kind": "report",
                               "name": report.stem, "title": report.stem,
                               "state": "report only (no run log)",
                               "updated": report.stat().st_mtime})
        results = folder / RESULTS_FILE
        summary = folder / SUMMARY_FILE
        newest = max([a["updated"] for a in audits] + [0.0] +
                     [p.stat().st_mtime for p in (results, summary) if p.is_file()])
        return {
            "id": self.token(folder),
            "name": folder.name,
            "kind": "benchmark" if results.is_file() else "audits",
            "results": self.token(results) if results.is_file() else None,
            "summary": self.token(summary) if summary.is_file() else None,
            "audits": audits,
            "updated": newest,
        }

    def _log_entry(self, path: Path) -> dict[str, Any]:
        try:
            events = read_events(path)
        except (OSError, ValueError) as exc:
            return {"token": self.token(path), "kind": "log", "name": path.name,
                    "title": path.name, "state": f"unreadable: {exc}",
                    "updated": path.stat().st_mtime}
        start = events[0] if events and events[0].get("kind") == "start" else {}
        end = events[-1] if events else {}
        if end.get("kind") == "finish":
            state = "finished"
        elif end.get("kind") == "stopped":
            state = "stopped"
        else:
            state = "running, or ended without saying so"
        cost = next((e.get("cost_usd") for e in reversed(events)
                     if e.get("kind") in ("finish", "stopped")), None)
        if cost is None:
            cost = next((e.get("cost_so_far_usd") for e in reversed(events)
                         if e.get("kind") == "model"), 0.0)
        return {
            "token": self.token(path), "kind": "log", "name": path.name,
            "title": start.get("title", path.name), "challenge": start.get("challenge"),
            "copy": start.get("copy"), "state": state, "cost_usd": cost,
            "events": len(events), "last_event_at": end.get("at"),
            "updated": path.stat().st_mtime,
        }

    def _map(self, path: Path) -> dict[str, Any] | None:
        """A proof map or an outline, as listed; None for any other JSON file."""
        if path.name.endswith(OUTLINE_SUFFIX):
            try:
                outline, _ = self._outline(path)
            except (OSError, ValueError):
                return None
            return {"token": self.token(path), "name": path.name, "kind": "outline",
                    "title": outline.parts[outline.result].name,
                    "parts": len(outline.parts)}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or data.get("format") != FORMAT_NAME:
            return None  # not a proof map; other JSON files are simply not listed
        source = data.get("lean_source")
        return {"token": self.token(path), "name": path.name, "kind": "map",
                "title": str(data.get("title", path.name)),
                "theorem": source.get("theorem") if isinstance(source, dict) else None}

    # --- one thing -------------------------------------------------------------------

    def log(self, token: str, after: int) -> dict[str, Any]:
        path = self.resolve(token, suffixes=(LOG_SUFFIX,))
        events = read_events(path, after)
        if after == 0 and events and (events[0].get("kind") != "start"
                                      or events[0].get("format") != LOG_FORMAT):
            raise NotAllowedError(f"'{token}' isn't a Scry run log.")
        return {"events": events}

    def text(self, token: str) -> dict[str, Any]:
        path = self.resolve(token, suffixes=(".md",))
        return {"name": path.name, "text": path.read_text(encoding="utf-8")}

    def results(self, token: str) -> dict[str, Any]:
        """A benchmark's results, scored again from the rows it saved, by today's rule (a
        results file keeps the score of the rule it was saved under)."""
        path = self.resolve(token, suffixes=(RESULTS_FILE,))
        try:
            challenges = read_results(path)
            for entries in challenges.values():
                for entry in entries:
                    planted = entry.get("planted_lines")
                    entry["saved_score"] = entry.get("score")
                    entry["score"] = (score_plant(saved_rows(entry["rows"]),
                                                  (int(planted[0]), int(planted[1])))
                                      if planted else None)
        except (BenchmarkError, KeyError, TypeError, IndexError) as exc:
            raise ValueError(f"{path.name} isn't a results file Scry can read: {exc}") from exc
        return {"challenges": challenges, "meanings": SCORE_MEANINGS}

    def proof_map(self, token: str) -> dict[str, Any]:
        path = self.resolve(token, suffixes=(".json",))
        proof_map = proof_map_from_dict(json.loads(path.read_text(encoding="utf-8")),
                                        source=path.name)
        wiring = check_wiring(proof_map)
        scan = scan_proof_map(proof_map)
        return {
            "map": proof_map_to_dict(proof_map),
            "order": proof_map.topological_order(),
            "wiring": {
                "summary": wiring.summary, "passed": wiring.passed,
                "goal_reached": wiring.goal_reached,
                "steps": {sid: {"status": v.status.value, "label": v.status.label,
                                "problems": [p.message for p in v.problems],
                                "notes": list(v.notes)}
                          for sid, v in wiring.verdicts.items()},
                "problems": [p.message for p in wiring.map_problems],
            },
            "blocks": [vars(b) for b in foldable_blocks(proof_map)],
            "scan": {
                "overview": scan.overview,
                "chokepoints": [vars(c) for c in scan.chokepoints],
                "knots": [vars(k) for k in scan.knots],
                "unused_steps": [vars(u) for u in scan.unused_steps],
            },
        }


    def outline(self, token: str) -> dict[str, Any]:
        outline, index = self._outline(self.resolve(token, suffixes=(OUTLINE_SUFFIX,)))
        theorem_maps = {m["theorem"]: m["token"] for m in self.overview()["maps"]
                        if m.get("theorem")}
        # The index is kept while the outline file is unchanged; the Lean files it was made
        # from can change at any time, so they are compared afresh on every request.
        return {**index, "changed_files": changed_files(outline),
                "maps": {part: theorem_maps[part] for part in index["ids"]
                         if part in theorem_maps}}

    def outline_part(self, token: str, part_id: str) -> dict[str, Any]:
        outline, _ = self._outline(self.resolve(token, suffixes=(OUTLINE_SUFFIX,)))
        part = outline.parts.get(part_id)
        if part is None:
            raise NotAllowedError(f"The outline has no part '{part_id}'.")
        return {"id": part.part_id, "name": part.name, "doc": part.doc,
                "statement": part.statement, "source": part.source,
                "unused_hypotheses": [vars(h) for h in part.unused_hypotheses],
                "route": _route(outline, part_id)}

    def _outline(self, path: Path) -> tuple[Outline, dict[str, Any]]:
        stat = path.stat()
        version = (stat.st_size, stat.st_mtime_ns)
        with self._outlines_lock:
            cached = self._outlines.get(path)
            if cached is not None and cached[0] == version:
                return cached[1], cached[2]
        data = json.loads(path.read_text(encoding="utf-8"))
        outline = outline_from_dict(data, source=path.name)
        index = _outline_index(outline)
        with self._outlines_lock:
            self._outlines[path] = (version, outline, index)
        return outline, index



def _outline_index(outline: Outline) -> dict[str, Any]:
    """Everything the outline view needs up front that depends on the outline file alone
    (whether its Lean files have changed since is added on each request). To keep this
    small enough for a phone, parts and files are referred to by their position in `ids`
    and `files`, a part's name is left out when it is the same as its ID, and "used by" is
    left for the page to work out. One part's text is fetched when it is chosen."""
    ids = list(outline.parts)
    number = {part_id: n for n, part_id in enumerate(ids)}
    files = sorted({p.file for p in outline.parts.values() if p.file is not None})
    file_number = {file: n for n, file in enumerate(files)}
    rests_on = outline.rests_on()
    parts = outline.parts
    return {
        "result": number[outline.result],
        "lean_version": outline.lean_version,
        "axioms": list(outline.axioms),
        "ids": ids,
        "files": files,
        "parts": [{
            "name": None if p.name == p.part_id else p.name,
            "kind": p.kind, "private": p.private,
            "file": None if p.file is None else file_number[p.file],
            "start_line": p.start_line, "lines": p.lines,
            "statement_uses": [number[u] for u in p.statement_uses],
            "body_uses": [number[u] for u in p.body_uses],
            "rests_on": len(rests_on[p.part_id]),
            "rests_on_lines": sum(parts[r].lines for r in rests_on[p.part_id]),
            "unused": [vars(h) for h in p.unused_hypotheses],
        } for p in parts.values()],
        "claim": [number[c] for c in outline.claim()],
        "meaning_kinds": sorted(MEANING_KINDS),
    }


def _route(outline: Outline, part_id: str) -> list[str]:
    """A shortest chain of "uses" from the result to `part_id`, both included."""
    came_from: dict[str, str | None] = {outline.result: None}
    queue = deque([outline.result])
    while queue:
        here = queue.popleft()
        if here == part_id:
            break
        for nxt in outline.parts[here].uses:
            if nxt not in came_from:
                came_from[nxt] = here
                queue.append(nxt)
    route: list[str] = []
    step: str | None = part_id if part_id in came_from else None
    while step is not None:
        route.append(step)
        step = came_from[step]
    return route[::-1]


def make_handler(library: Library, access: PublicAccess | None = None,
                 ) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "ScryWorkbench"

        def log_message(self, format: str, *args: Any) -> None:
            pass  # quiet: the terminal is for the person

        def do_GET(self) -> None:
            url = urlparse(self.path)
            refusal = self._refusal(url.path)
            if refusal is not None:
                self._send(HTTPStatus.FORBIDDEN, {"error": refusal})
                return
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            api = f"{WORKBENCH}api/"
            try:
                if url.path.startswith(api):
                    self._send(HTTPStatus.OK, self._api(url.path[len(api):], query))
                elif url.path == WORKBENCH.rstrip("/"):
                    self._redirect(WORKBENCH)
                elif url.path.startswith(WORKBENCH):
                    self._static(url.path[len(WORKBENCH):])
                else:
                    self._public(url.path)
            except NotAllowedError as exc:
                self._send(HTTPStatus.NOT_FOUND, {"error": str(exc)})
            except (ValueError, OSError) as exc:
                self._send(HTTPStatus.BAD_REQUEST, {"error": f"Couldn't read that: {exc}"})

        def _refusal(self, path: str) -> str | None:
            hosts = self.headers.get_all("Host") or []
            host = hosts[0].strip().casefold() if len(hosts) == 1 else ""
            if _HOST.match(host):
                return None
            if access is not None and host == access.host:
                if public_file(path) is not None:
                    return None
                return access.refusal(self.headers.get_all(TOKEN_HEADER) or [])
            return "This workbench only answers requests addressed to this machine."

        def _api(self, name: str, query: dict[str, str]) -> dict[str, Any]:
            if name == "overview":
                return library.overview()
            file = query.get("file", "")
            if name == "log":
                after = query.get("after", "0")
                if not after.isdigit():
                    raise NotAllowedError("'after' must be a whole number.")
                return library.log(file, int(after))
            if name == "text":
                return library.text(file)
            if name == "results":
                return library.results(file)
            if name == "map":
                return library.proof_map(file)
            if name == "outline":
                return library.outline(file)
            if name == "outline-part":
                return library.outline_part(file, query.get("part", ""))
            raise NotAllowedError(f"There is no '{name}' here.")

        def _static(self, name: str) -> None:
            file = (STATIC / (name or "index.html")).resolve()
            if not file.is_relative_to(STATIC.resolve()) or not file.is_file():
                raise NotAllowedError(f"There is no page '{WORKBENCH}{name}'.")
            self._file(file, _WORKBENCH_POLICY)

        def _public(self, path: str) -> None:
            file = public_file(path)
            if file is None:
                raise NotAllowedError(f"There is no page '{path}'.")
            self._file(file, _PUBLIC_POLICY)

        def _file(self, file: Path, policy: str) -> None:
            kind = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            if file.suffix == ".js":
                kind = "text/javascript"
            self._raw(HTTPStatus.OK, file.read_bytes(), f"{kind}; charset=utf-8", policy)

        def _redirect(self, to: str) -> None:
            self.send_response(HTTPStatus.MOVED_PERMANENTLY)
            self.send_header("Location", to)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _send(self, status: HTTPStatus, data: dict[str, Any]) -> None:
            body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
            self._raw(status, body, "application/json; charset=utf-8", _WORKBENCH_POLICY)

        def _raw(self, status: HTTPStatus, body: bytes, kind: str, policy: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", policy)
            self.end_headers()
            self.wfile.write(body)

    return Handler


def serve(library: Library, port: int, access: PublicAccess | None = None,
          ) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(library, access))
