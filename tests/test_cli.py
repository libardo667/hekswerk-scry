"""The command line, end to end."""

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hekswerk_scry.cli import main
from hekswerk_scry.files import save_proof_map
from tests.helpers import example, make_map, make_step


def run(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(args))
    return code, out.getvalue(), err.getvalue()


class TestCommandLine(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.map_file = Path(self.folder.name) / "example.json"
        save_proof_map(example(), self.map_file)

    def test_demo_runs_and_ends_with_the_honest_label(self) -> None:
        code, out, _ = run("demo")
        self.assertEqual(code, 0)
        self.assertIn("Status: Rejected", out)
        self.assertIn("Status: Ready to swap", out)
        self.assertIn("nothing here counts as proven", out)
        self.assertNotIn("Lean-checked", out)

    def test_check_exit_code_follows_the_result(self) -> None:
        code, out, _ = run("check", str(self.map_file))
        self.assertEqual(code, 0)
        self.assertIn("Wiring checked (not proven)", out)

        broken = Path(self.folder.name) / "broken.json"
        save_proof_map(make_map([make_step("a", "p", ["nowhere"])], "a"), broken)
        code, out, _ = run("check", str(broken))
        self.assertEqual(code, 1)
        self.assertIn("[Wiring broken] a", out)

    def test_scan_and_what_if(self) -> None:
        code, out, _ = run("scan", str(self.map_file))
        self.assertEqual(code, 0)
        self.assertIn("knot-shift-positive", out)
        code, out, _ = run("what-if", str(self.map_file), "--drop-fact", "x >= 0")
        self.assertEqual(code, 0)
        self.assertIn("breaks 5 step(s)", out)

    def test_chat_commands_work_without_calling_the_model(self) -> None:
        typed = io.StringIO("/cards\n/evidence E1\n/apply C1 New.lean\n/cost\n/quit\n")
        env = {**os.environ, "OPENROUTER_API_KEY": "sk-or-test", "SCRY_MODEL": "test/model"}
        with mock.patch.dict(os.environ, env), mock.patch("sys.stdin", typed):
            code, out, _ = run("chat", str(self.map_file))
        self.assertEqual(code, 0)
        self.assertIn("with test/model (effort high)", out)
        self.assertIn("only Lean's checks count as proof", out)
        self.assertIn("The helper hasn't drafted any cards yet.", out)
        self.assertIn("There is no evidence E1.", out)
        self.assertIn("There is no card C1.", out)
        self.assertIn("has cost $0.0000 so far", out)

    def test_errors_are_reported_plainly(self) -> None:
        code, _, err = run("check", str(Path(self.folder.name) / "missing.json"))
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("Error: Couldn't open"))
        code, _, err = run("what-if", str(self.map_file), "--remove-step", "ghost")
        self.assertEqual(code, 2)
        self.assertIn("no step 'ghost'", err)


if __name__ == "__main__":
    unittest.main()
