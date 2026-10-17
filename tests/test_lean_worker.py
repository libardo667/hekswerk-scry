"""The kept-running Lean process and the skipped builds, with a stand-in for Lean.

The stand-in `lake` speaks the same protocol as `scry-export --serve`, and reports its
process id so the tests can see when the process was restarted. Real Lean is tested in
`lean_tests/test_lean_worker.py`.
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from hekswerk_scry.lean import worker as worker_module
from hekswerk_scry.lean.worker import LeanWorker, LeanWorkerError, worker_for
from hekswerk_scry.lean.workspace import LeanWorkspace

STAND_IN = f"""#!{sys.executable}
import json, os, sys, time
if sys.argv[1:2] == ["build"]:
    with open(os.path.join(os.path.dirname(sys.argv[0]), "builds.txt"), "a") as log:
        log.write(" ".join(sys.argv[2:]) + "\\n")
    sys.exit(0)
for line in sys.stdin:
    request = json.loads(line)
    reply = {{"id": request["id"], "result": {{"pid": os.getpid()}}, "printed": ""}}
    theorem = request["theorem"]
    if theorem == "slow":
        time.sleep(30)
    if theorem == "prints":
        print("printed by the file itself", flush=True)
        reply["printed"] = "and some captured output"
    if theorem == "wrong-id":
        reply["id"] = -1
    if theorem == "fails":
        reply = {{"id": request["id"], "error": "something went wrong", "printed": ""}}
    print("scry-reply " + json.dumps(reply), flush=True)
"""


class WorkerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        lake = self.root / "lake"
        lake.write_text(STAND_IN, encoding="utf-8")
        lake.chmod(0o755)
        self.exporter = self.root / "scry-export"
        self.exporter.write_bytes(b"exporter build 1")
        (self.root / "lean-toolchain").write_text("leanprover/lean4:v4.34.1\n", encoding="utf-8")
        self.build_log = self.root / "builds.txt"
        self.ws = LeanWorkspace(root=self.root, lake=lake, exporter=self.exporter)
        self.file = self.root / "Check.lean"
        self.file.write_text("theorem t : True := trivial\n", encoding="utf-8")
        self.worker = LeanWorker(self.ws)
        self.addCleanup(self.worker.close)

    def pid(self, theorem: str = "t", timeout: float = 20) -> int:
        reply = self.worker.ask("check", self.file, theorem, timeout=timeout)
        assert reply.result is not None
        return int(reply.result["pid"])


class TestKeptRunningLean(WorkerTestCase):
    def test_one_process_answers_many_checks(self) -> None:
        self.assertEqual(self.pid(), self.pid())

    def test_a_rebuilt_exporter_means_a_new_process(self) -> None:
        first = self.pid()
        self.exporter.write_bytes(b"exporter build 2")
        self.assertNotEqual(self.pid(), first)

    def test_new_build_output_means_a_new_process(self) -> None:
        first = self.pid()
        built = self.root / ".lake" / "build" / "lib" / "lean" / "Thing.olean"
        built.parent.mkdir(parents=True)
        built.write_bytes(b"olean")
        second = self.pid()
        self.assertNotEqual(second, first)
        later = time.time() + 5
        os.utime(built, (later, later))
        self.assertNotEqual(self.pid(), second)

    def test_a_changed_package_list_means_a_new_process(self) -> None:
        first = self.pid()
        (self.root / "lake-manifest.json").write_text("{}", encoding="utf-8")
        self.assertNotEqual(self.pid(), first)

    def test_running_out_of_time_stops_the_process(self) -> None:
        first = self.pid()
        reply = self.worker.ask("check", self.file, "slow", timeout=0.5)
        self.assertTrue(reply.timed_out)
        self.assertIsNone(reply.result)
        self.assertNotEqual(self.pid(), first)

    def test_printed_output_is_kept_apart_from_the_reply(self) -> None:
        reply = self.worker.ask("check", self.file, "prints", timeout=20)
        self.assertEqual(reply.printed,
                         ("printed by the file itself", "and some captured output"))
        self.assertIn("pid", reply.result or {})

    def test_failures_are_reported_not_guessed_around(self) -> None:
        with self.assertRaisesRegex(LeanWorkerError, "something went wrong"):
            self.worker.ask("check", self.file, "fails", timeout=20)
        with self.assertRaisesRegex(LeanWorkerError, "different request"):
            self.worker.ask("check", self.file, "wrong-id", timeout=20)

    def test_it_can_be_switched_off(self) -> None:
        self.assertIsNotNone(worker_for(self.ws))
        with mock.patch.dict(os.environ, {worker_module.SWITCH: "off"}):
            self.assertIsNone(worker_for(self.ws))
        worker_module.close_all()


class TestSkippedBuilds(WorkerTestCase):
    def builds(self) -> list[str]:
        if not self.build_log.exists():
            return []
        return self.build_log.read_text(encoding="utf-8").splitlines()

    def test_imports_are_built_again_only_when_a_source_changes(self) -> None:
        (self.root / "Proj").mkdir()
        module = self.root / "Proj" / "Basic.lean"
        module.write_text("def x := 1\n", encoding="utf-8")
        checked = self.root / "Uses.lean"
        checked.write_text("import Proj.Basic\n", encoding="utf-8")
        self.ws.build_imports(checked)
        self.ws.build_imports(checked)
        self.assertEqual(self.builds(), ["Proj.Basic"])
        # Scry's own scratch files don't count: nothing imports them.
        scratch = self.root / ".scry-runs" / "abc" / "Check.lean"
        scratch.parent.mkdir(parents=True, exist_ok=True)
        scratch.write_text("theorem t : True := trivial\n", encoding="utf-8")
        self.ws.build_imports(checked)
        self.assertEqual(len(self.builds()), 1)
        # An edit anywhere in the project's own sources does.
        module.write_text("def x := 22\n", encoding="utf-8")
        self.ws.build_imports(checked)
        self.assertEqual(len(self.builds()), 2)
        other = self.root / "Proj" / "Other.lean"
        other.write_text("def y := 1\n", encoding="utf-8")
        self.ws.build_imports(checked)
        self.assertEqual(len(self.builds()), 3)
        (self.root / "lake-manifest.json").write_text(json.dumps({}), encoding="utf-8")
        self.ws.build_imports(checked)
        self.assertEqual(len(self.builds()), 4)


if __name__ == "__main__":
    unittest.main()
