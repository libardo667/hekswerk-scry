"""Stopping a program that ran out of time must stop everything it started.

`lake env lean ...` runs Lean as a child process. Before this was fixed, a timeout
stopped only `lake`, and the Lean underneath kept running (in one case for five hours, in
an endless loop). The stand-in `lake` here does the same: it starts a child that would
sleep for a minute, writes the child's process id down, and waits for it. Every place
Scry runs `lake` is run with a short time limit, and the child must be gone afterwards.
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from hekswerk_scry.lean import worker as worker_module
from hekswerk_scry.lean.importer import LeanImportError, run_exporter
from hekswerk_scry.lean.processes import run_program
from hekswerk_scry.lean.runner import check_file
from hekswerk_scry.lean.statement import StatementError, read_statement
from hekswerk_scry.lean.workspace import LeanSetupError, LeanWorkspace

SLOW_LAKE = f"""#!{sys.executable}
import os, subprocess, sys
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
with open(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "children.txt"), "a") as f:
    f.write(f"{{child.pid}}\\n")
sys.exit(child.wait())
"""


def alive(pid: int) -> bool:
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        try:
            if Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z":
                return False  # stopped; only its exit status is left to collect
        except FileNotFoundError:
            return False
        time.sleep(0.1)
    return True


class TestTimeoutsStopEverything(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        lake = self.root / "lake"
        lake.write_text(SLOW_LAKE, encoding="utf-8")
        lake.chmod(0o755)
        exporter = self.root / "scry-export"
        exporter.write_bytes(b"exporter")
        (self.root / "lean-toolchain").write_text("leanprover/lean4:v4.34.1\n", encoding="utf-8")
        (self.root / "Proj").mkdir()
        (self.root / "Proj" / "Basic.lean").write_text("def x := 1\n", encoding="utf-8")
        self.file = self.root / "Uses.lean"
        self.file.write_text("theorem t : True := trivial\n", encoding="utf-8")
        self.ws = LeanWorkspace(root=self.root, lake=lake, exporter=exporter)
        switch = mock.patch.dict(os.environ, {worker_module.SWITCH: "off"})
        switch.start()
        self.addCleanup(switch.stop)

    def children(self) -> list[int]:
        listing = self.root / "children.txt"
        for _ in range(50):
            if listing.exists() and listing.read_text(encoding="utf-8").strip():
                break
            time.sleep(0.1)
        return [int(n) for n in listing.read_text(encoding="utf-8").split()]

    def assert_nothing_left_running(self) -> None:
        started = self.children()
        self.assertTrue(started)
        self.assertEqual([pid for pid in started if alive(pid)], [])

    def test_run_program(self) -> None:
        done = run_program([str(self.ws.lake), "anything"], timeout=1)
        self.assertTrue(done.timed_out)
        self.assertIsNone(done.exit_code)
        self.assert_nothing_left_running()

    def test_a_fresh_lean_check(self) -> None:
        check = check_file(self.ws, self.file, "t", fresh=True, timeout=1)
        self.assertFalse(check.passed)
        self.assertIn("longer than 1 seconds", check.problems[0])
        self.assert_nothing_left_running()

    def test_a_proof_map_export(self) -> None:
        with self.assertRaisesRegex(LeanImportError, "longer than 1 seconds"):
            run_exporter(self.ws, self.file, "t", timeout=1)
        self.assert_nothing_left_running()

    def test_a_statement_read(self) -> None:
        with self.assertRaisesRegex(StatementError, "longer than 1 seconds"):
            read_statement(self.ws, self.file, "t", timeout=1)
        self.assert_nothing_left_running()

    def test_building_imports(self) -> None:
        self.file.write_text("import Proj.Basic\n", encoding="utf-8")
        with self.assertRaisesRegex(LeanSetupError, "longer than 1 seconds"):
            self.ws.build_imports(self.file, timeout=1)
        self.assert_nothing_left_running()


if __name__ == "__main__":
    unittest.main()
