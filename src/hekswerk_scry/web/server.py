"""The browser workbench's server: a read-only window onto what Scry has done.

`scry serve` shows audits as they run (from their run logs), benchmark results, audit
reports, and proof maps. It changes nothing and starts nothing: no Lean runs, no model
calls, no file writes. Starting work from the browser can come later.

Safety:
- It listens on 127.0.0.1 only, and refuses requests whose Host header names anything but
  this machine, so a web page elsewhere can't reach it through a DNS trick. The one
  exception, when it is set up, is a public name carried here by a Cloudflare Tunnel; those
  requests are answered only with a valid Cloudflare Access sign-in (see `access.py`).
- Every file it serves is named by a token, "<source>:<path inside it>", that must resolve
  to a file of the expected kind inside one of the folders it was given. Anything else is
  refused, with a plain message.

Standard library only, like the rest of Scry's runtime.
"""

import json
import mimetypes
import re
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from hekswerk_scry.ai.run_log import LOG_FORMAT, LOG_SUFFIX, read_events
from hekswerk_scry.checker import check_wiring, scan_proof_map
from hekswerk_scry.files import FORMAT_NAME, proof_map_from_dict, proof_map_to_dict
from hekswerk_scry.web.access import TOKEN_HEADER, PublicAccess
from hekswerk_scry.web.blocks import foldable_blocks

STATIC = Path(__file__).parent / "static"
RESULTS_FILE = "results.json"
SUMMARY_FILE = "summary.md"
_HOST = re.compile(r"^(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$")


class NotAllowedError(ValueError):
    """A request for something the workbench won't show. The message says why."""


@dataclass(frozen=True)
class Source:
    """A folder the workbench may read: audit runs, or proof maps."""

    kind: str  # "runs" or "maps"
    root: Path


class Library:
    def __init__(self, sources: list[Source]) -> None:
        self.sources = [Source(s.kind, s.root.resolve()) for s in sources]

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
        for source in self.sources:
            if not source.root.is_dir():
                continue
            if source.kind == "runs":
                folders = {p.parent for p in source.root.rglob(f"*{LOG_SUFFIX}")}
                folders |= {p.parent for p in source.root.rglob(RESULTS_FILE)}
                folders |= {p.parent for p in source.root.rglob("*.md")}
                runs += [self._folder(folder) for folder in sorted(folders)]
            else:
                maps += [m for p in sorted(source.root.rglob("*.json")) if (m := self._map(p))]
        runs.sort(key=lambda r: r["updated"], reverse=True)
        return {"runs": runs, "maps": maps}

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
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or data.get("format") != FORMAT_NAME:
            return None  # not a proof map; other JSON files are simply not listed
        return {"token": self.token(path), "name": path.name,
                "title": str(data.get("title", path.name))}

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
        path = self.resolve(token, suffixes=(RESULTS_FILE,))
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data

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


def make_handler(library: Library, access: PublicAccess | None = None,
                 ) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "ScryWorkbench"

        def log_message(self, format: str, *args: Any) -> None:
            pass  # quiet: the terminal is for the person

        def do_GET(self) -> None:
            refusal = self._refusal()
            if refusal is not None:
                self._send(HTTPStatus.FORBIDDEN, {"error": refusal})
                return
            url = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                if url.path.startswith("/api/"):
                    self._send(HTTPStatus.OK, self._api(url.path[5:], query))
                else:
                    self._static(url.path)
            except NotAllowedError as exc:
                self._send(HTTPStatus.NOT_FOUND, {"error": str(exc)})
            except (ValueError, OSError) as exc:
                self._send(HTTPStatus.BAD_REQUEST, {"error": f"Couldn't read that: {exc}"})

        def _refusal(self) -> str | None:
            hosts = self.headers.get_all("Host") or []
            host = hosts[0].strip().casefold() if len(hosts) == 1 else ""
            if _HOST.match(host):
                return None
            if access is not None and host == access.host:
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
            raise NotAllowedError(f"There is no '{name}' here.")

        def _static(self, path: str) -> None:
            name = "index.html" if path in ("", "/") else path.lstrip("/")
            file = (STATIC / name).resolve()
            if not file.is_relative_to(STATIC.resolve()) or not file.is_file():
                raise NotAllowedError(f"There is no page '{path}'.")
            body = file.read_bytes()
            kind = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            if file.suffix == ".js":
                kind = "text/javascript"
            self._raw(HTTPStatus.OK, body, f"{kind}; charset=utf-8")

        def _send(self, status: HTTPStatus, data: dict[str, Any]) -> None:
            body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
            self._raw(status, body, "application/json; charset=utf-8")

        def _raw(self, status: HTTPStatus, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self'; script-src 'self'; "
                             "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def serve(library: Library, port: int, access: PublicAccess | None = None,
          ) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(library, access))
