"""The browser workbench's server: what it shows, and what it refuses. Runs a real server
on a free port; no browser."""

import http.client
import itertools
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

from hekswerk_scry.ai.run_log import LOG_FORMAT, LOG_SUFFIX, RunLog
from hekswerk_scry.files import save_outline
from hekswerk_scry.web.access import TOKEN_HEADER
from hekswerk_scry.web.server import Library, NotAllowedError, Source, serve
from tests.test_outline import example_outline
from tests.test_web_access import public_access
from tests.test_web_access import token as sign_in

EXAMPLES = Path(__file__).parents[1] / "src" / "hekswerk_scry" / "examples"


def write_log(path: Path, ending: str | None) -> None:
    log = RunLog(path)
    log.write(
        "start",
        format=LOG_FORMAT,
        title="Audit of Thing",
        challenge="Thing",
        copy="control",
        statement_text="x\n",
    )
    log.write("model", text="", tool_calls=["read_paper"], cost_usd=0.1, cost_so_far_usd=0.1)
    if ending == "finish":
        log.write("finish", answer="done", cost_usd=0.25)
    elif ending == "stopped":
        log.write("stopped", reason="AIProviderError: no credit", cost_usd=0.1)


class WorkbenchCase(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        runs = self.root / "runs"
        (runs / "bench").mkdir(parents=True)
        write_log(runs / "bench" / f"Thing--control-20261018-000000{LOG_SUFFIX}", "finish")
        write_log(runs / "bench" / f"Thing--p-20261018-000001{LOG_SUFFIX}", None)
        write_log(runs / "bench" / f"Other--control-20261018-000002{LOG_SUFFIX}", "stopped")
        (runs / "bench" / "results.json").write_text(json.dumps({"Thing": []}), encoding="utf-8")
        (runs / "bench" / "summary.md").write_text("# Summary\n", encoding="utf-8")
        (runs / "bench" / "Thing--control.md").write_text("logged, so hidden", encoding="utf-8")
        (runs / "bench" / "Old--control.md").write_text("# An old report\n", encoding="utf-8")
        maps = self.root / "maps"
        maps.mkdir()
        shutil.copy(EXAMPLES / "shifted_fraction.json", maps / "map.json")
        (maps / "not-a-map.json").write_text('{"hello": 1}', encoding="utf-8")
        self.outline = example_outline(self.root / "project")
        save_outline(self.outline, maps / "example.outline.json")
        (self.root / "secret.md").write_text("outside every folder", encoding="utf-8")
        self.library = Library([Source("runs", runs), Source("maps", maps)])


class TestLibrary(WorkbenchCase):
    def test_overview_lists_runs_states_and_maps(self) -> None:
        overview = self.library.overview()
        [run] = overview["runs"]
        self.assertEqual(run["kind"], "benchmark")
        states = {a["name"]: a["state"] for a in run["audits"]}
        self.assertEqual(
            states,
            {
                f"Other--control-20261018-000002{LOG_SUFFIX}": "stopped",
                f"Thing--control-20261018-000000{LOG_SUFFIX}": "finished",
                f"Thing--p-20261018-000001{LOG_SUFFIX}": "running, or ended without saying so",
                "Old--control": "report only (no run log)",
            },
        )
        costs = {a["name"]: a.get("cost_usd") for a in run["audits"] if a["kind"] == "log"}
        self.assertEqual(sorted(costs.values()), [0.1, 0.1, 0.25])
        self.assertEqual([m["name"] for m in overview["maps"]], ["map.json"])
        self.assertEqual([(o["name"], o["title"], o["parts"]) for o in overview["outlines"]],
                         [("example.outline.json", "OutlineExample.result", 11)])

    def test_only_files_of_the_right_kind_inside_the_folders_are_served(self) -> None:
        good = self.library.token(self.root / "runs" / "bench" / "Old--control.md")
        self.assertEqual(self.library.text(good)["text"], "# An old report\n")
        for token, message in [
            ("0:../secret.md", "knows about"),
            ("0:bench/../../secret.md", "knows about"),
            (f"0:{self.root}/secret.md", "knows about"),
            ("7:bench/Old--control.md", "knows about"),
            ("bench/Old--control.md", "knows about"),
            ("0:bench/results.json", "kind of file"),
            ("0:bench/missing.md", "knows about"),
        ]:
            with self.subTest(token), self.assertRaisesRegex(NotAllowedError, message):
                self.library.text(token)
        with self.assertRaisesRegex(NotAllowedError, "kind of file"):
            self.library.log(good, 0)
        with self.assertRaisesRegex(NotAllowedError, "isn't inside"):
            self.library.token(self.root / "secret.md")

    def test_a_log_is_read_from_a_point_on(self) -> None:
        token = self.library.token(
            self.root / "runs" / "bench" / f"Thing--control-20261018-000000{LOG_SUFFIX}"
        )
        self.assertEqual(
            [e["kind"] for e in self.library.log(token, 0)["events"]], ["start", "model", "finish"]
        )
        self.assertEqual([e["kind"] for e in self.library.log(token, 2)["events"]], ["finish"])

    def test_a_proof_map_comes_with_its_checks(self) -> None:
        data = self.library.proof_map("1:map.json")
        self.assertTrue(data["wiring"]["passed"])
        self.assertEqual(set(data["order"]), {s["id"] for s in data["map"]["steps"]})
        self.assertEqual(len(data["scan"]["chokepoints"]), 1)
        self.assertEqual(data["blocks"], [])  # the bundled example has no Lean positions


class TestOutlines(WorkbenchCase):
    def token(self) -> str:
        return self.library.token(self.root / "maps" / "example.outline.json")

    def test_the_index_is_the_outline_in_short(self) -> None:
        index = self.library.outline(self.token())
        ids = index["ids"]
        self.assertEqual(ids, list(self.outline.parts))
        self.assertEqual(ids[index["result"]], self.outline.result)
        rests_on = self.outline.rests_on()
        for part_id, entry in zip(ids, index["parts"], strict=True):
            part = self.outline.parts[part_id]
            with self.subTest(part_id):
                self.assertEqual(entry["name"] or part_id, part.name)
                file = None if entry["file"] is None else index["files"][entry["file"]]
                self.assertEqual(file, part.file)
                self.assertEqual([ids[u] for u in entry["statement_uses"]],
                                 list(part.statement_uses))
                self.assertEqual([ids[u] for u in entry["body_uses"]], list(part.body_uses))
                self.assertEqual(entry["rests_on"], len(rests_on[part_id]))
                self.assertEqual(entry["rests_on_lines"],
                                 sum(self.outline.parts[r].lines for r in rests_on[part_id]))
                self.assertEqual(len(entry["unused"]), len(part.unused_hypotheses))
        self.assertEqual([ids[c] for c in index["claim"]], list(self.outline.claim()))
        self.assertEqual(index["changed_files"], [])

    def test_a_part_comes_with_its_text_and_a_route_from_the_result(self) -> None:
        for part_id, part in self.outline.parts.items():
            answer = self.library.outline_part(self.token(), part_id)
            self.assertEqual((answer["source"], answer["statement"]), (part.source, part.statement))
            route = answer["route"]
            self.assertEqual((route[0], route[-1]), (self.outline.result, part_id))
            for here, nxt in itertools.pairwise(route):
                self.assertIn(nxt, self.outline.parts[here].uses)
        with self.assertRaises(NotAllowedError):
            self.library.outline_part(self.token(), "OutlineExample.nothing")

    def test_a_theorem_s_step_by_step_map_is_linked(self) -> None:
        data = json.loads((self.root / "maps" / "map.json").read_text(encoding="utf-8"))
        data["lean_source"] = {"file": "Examples/Outline.lean", "theorem": "OutlineExample.loose",
                               "file_sha256": "0" * 64}
        (self.root / "maps" / "map.json").write_text(json.dumps(data), encoding="utf-8")
        map_token = self.library.token(self.root / "maps" / "map.json")
        self.assertEqual(self.library.outline(self.token())["maps"],
                         {"OutlineExample.loose": map_token})

    def test_a_changed_outline_file_is_read_again(self) -> None:
        version = self.outline.lean_version
        self.assertEqual(self.library.outline(self.token())["lean_version"], version)
        path = self.root / "maps" / "example.outline.json"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace(f'"lean_version": "{version}"', '"lean_version": "9.9.9"'),
                        encoding="utf-8")
        self.assertEqual(self.library.outline(self.token())["lean_version"], "9.9.9")

    def test_only_outline_files_are_read_as_outlines(self) -> None:
        with self.assertRaises(NotAllowedError):
            self.library.outline(self.library.token(self.root / "maps" / "map.json"))


class TestServer(WorkbenchCase):
    def setUp(self) -> None:
        super().setUp()
        self.server = serve(self.library, 0)
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self, path: str, host: str | None = None,
            extra: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request("GET", path,
                           headers={"Host": host or f"127.0.0.1:{self.port}", **(extra or {})})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, dict(response.getheaders()), body

    def json(self, path: str) -> tuple[int, Any]:
        status, _, body = self.get(path)
        return status, json.loads(body)

    def test_it_listens_on_this_machine_only(self) -> None:
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_requests_for_other_sites_are_refused(self) -> None:
        for host in ("evil.example", "evil.example:80", "127.0.0.1.evil.example"):
            with self.subTest(host):
                status, _, body = self.get("/api/overview", host=host)
                self.assertEqual(status, 403)
                self.assertIn(b"addressed to this machine", body)
        for host in (f"localhost:{self.port}", f"127.0.0.1:{self.port}"):
            self.assertEqual(self.get("/api/overview", host=host)[0], 200)

    def test_pages_and_answers(self) -> None:
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b'<script type="module" src="/app.js">', body)
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        status, headers, _ = self.get("/app.js")
        self.assertEqual((status, headers["Content-Type"]), (200, "text/javascript; charset=utf-8"))
        status, data = self.json("/api/overview")
        self.assertEqual((status, len(data["runs"])), (200, 1))

    def test_refusals_are_plain_and_leak_nothing(self) -> None:
        for path in (
            "/../secret.md",
            "/%2e%2e/secret.md",
            "/api/text?file=0:../secret.md",
            "/api/log?file=0:x&after=-1",
            "/api/nothing",
        ):
            with self.subTest(path):
                status, data = self.json(path)
                self.assertIn(status, (400, 404))
                self.assertNotIn("outside every folder", json.dumps(data))
                self.assertTrue(data["error"])


class TestServerWithPublicName(TestServer):
    """Everything TestServer checks still holds, and the public name needs a sign-in."""

    def setUp(self) -> None:
        WorkbenchCase.setUp(self)
        self.access, _, _ = public_access()
        self.server = serve(self.library, 0, self.access)
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def test_the_public_name_needs_a_valid_sign_in(self) -> None:
        public = "scry.hekswerk.com"
        status, _, body = self.get("/api/overview", host=public)
        self.assertEqual(status, 403)
        self.assertIn(b"Sign in through Cloudflare Access", body)
        expired = sign_in(claims={"exp": 0})
        status, _, body = self.get("/api/overview", host=public, extra={TOKEN_HEADER: expired})
        self.assertEqual(status, 403)
        self.assertNotIn(b"runs", body)
        status, _, body = self.get("/api/overview", host=public, extra={TOKEN_HEADER: sign_in()})
        self.assertEqual(status, 200)
        self.assertIn(b"runs", body)
        status, _, _ = self.get("/", host="SCRY.hekswerk.com", extra={TOKEN_HEADER: sign_in()})
        self.assertEqual(status, 200)

    def test_a_sign_in_opens_only_the_public_name(self) -> None:
        for host in ("evil.example", "scry.hekswerk.com.evil.example", "workbench.hekswerk.com"):
            with self.subTest(host):
                status, _, _ = self.get("/api/overview", host=host,
                                        extra={TOKEN_HEADER: sign_in()})
                self.assertEqual(status, 403)


class TestServerWithoutPublicName(WorkbenchCase):
    def test_a_sign_in_means_nothing_when_no_public_name_is_set_up(self) -> None:
        server = serve(self.library, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
        connection.request("GET", "/api/overview",
                           headers={"Host": "scry.hekswerk.com", TOKEN_HEADER: sign_in()})
        self.assertEqual(connection.getresponse().status, 403)
        connection.close()


if __name__ == "__main__":
    unittest.main()
