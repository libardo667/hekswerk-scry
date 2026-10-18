"""Run logs: what people follow an audit by. No Lean, and a scripted stand-in for the model."""

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from hekswerk_scry.ai.audit import run_audit
from hekswerk_scry.ai.openrouter import AIProviderError, OpenRouterClient
from hekswerk_scry.ai.run_log import LOG_SUFFIX, RunLog, read_events
from tests.test_ai_helper import SETTINGS, ScriptedTransport, reply, tool_call
from tests.test_statement_tools import ToolboxCase


class TestRunLogFile(unittest.TestCase):
    def test_events_are_numbered_and_read_back_after_a_point(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            log = RunLog(Path(folder) / f"a{LOG_SUFFIX}")
            for n in range(5):
                log.write("model", text=f"step {n}")
            events = read_events(log.path)
            self.assertEqual([e["seq"] for e in events], [1, 2, 3, 4, 5])
            self.assertEqual(
                [e["text"] for e in read_events(log.path, after=3)], ["step 3", "step 4"]
            )

    def test_a_line_still_being_written_is_left_out(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            log = RunLog(Path(folder) / f"a{LOG_SUFFIX}")
            log.write("start", title="t")
            with log.path.open("a", encoding="utf-8") as stream:
                stream.write('{"seq": 2, "kind": "mod')  # half a line
            self.assertEqual([e["seq"] for e in read_events(log.path)], [1])

    def test_a_log_is_never_written_over(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / f"a{LOG_SUFFIX}"
            RunLog(path).write("start")
            with self.assertRaisesRegex(ValueError, "never written over"):
                RunLog(path)
            with self.assertRaisesRegex(ValueError, "must end in"):
                RunLog(Path(folder) / "a.json")


class TestAuditsAreLogged(ToolboxCase):
    SCRIPT = (
        reply(
            {
                "content": "Reading the statement first.",
                "tool_calls": [
                    tool_call("1", "read_lean_lines", {"first_line": 1, "last_line": 3}),
                    tool_call(
                        "2",
                        "record_verdict",
                        {
                            "item": "conclusion",
                            "paper_says": "p",
                            "lean_says": "l",
                            "verdict": "differs",
                            "affects_main_result": True,
                            "lean_first_line": 2,
                            "lean_last_line": 2,
                            "evidence": ["E1"],
                        },
                    ),
                ],
            },
            cost=0.02,
        ),
        reply(
            {
                "content": "",
                "tool_calls": [
                    tool_call(
                        "3",
                        "record_verdict",
                        {
                            "item": "x",
                            "paper_says": "p",
                            "lean_says": "l",
                            "verdict": "fine",
                            "affects_main_result": False,
                            "lean_first_line": 1,
                            "lean_last_line": 1,
                            "evidence": ["E1"],
                        },
                    ),
                ],
            },
            cost=0.01,
        ),
        reply({"content": "The conclusion differs [E1]."}, cost=0.005),
    )

    def run_with(self, log: RunLog | None) -> tuple[Any, ScriptedTransport]:
        transport = ScriptedTransport(list(self.SCRIPT))
        client = OpenRouterClient(SETTINGS, transport=transport, sleep=lambda _: None)
        audit = run_audit(
            client,
            self.box,
            "system prompt",
            "Thing",
            ("Paper",),
            log,
            {"title": "Audit of Thing", "copy": None},
        )
        return audit, transport

    def test_everything_the_audit_did_is_in_the_log_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            log = RunLog(Path(folder) / f"thing{LOG_SUFFIX}")
            audit, _ = self.run_with(log)
            events = read_events(log.path)
        kinds = [e["kind"] for e in events]
        self.assertEqual(
            kinds,
            [
                "start",
                "model",
                "evidence",
                "evidence",
                "verdict",
                "model",
                "evidence",
                "model",
                "finish",
            ],
        )
        start, finish = events[0], events[-1]
        self.assertEqual(
            start["statement_text"], self.box.statement_file.read_text(encoding="utf-8")
        )
        self.assertEqual((start["title"], start["model"]), ("Audit of Thing", SETTINGS.model))
        # Conservation: every piece of evidence appears exactly once, in order, unchanged.
        logged = [(e["id"], e["tool"], e["result"]) for e in events if e["kind"] == "evidence"]
        self.assertEqual(
            logged, [(e.evidence_id, e.tool, e.result) for e in audit.toolbox.evidence]
        )
        # Only accepted rows are logged as verdicts, and all of them are.
        verdicts = [e for e in events if e["kind"] == "verdict"]
        self.assertEqual(
            [(v["item"], v["verdict"]) for v in verdicts],
            [(r.item, r.verdict) for r in audit.toolbox.verdicts],
        )
        self.assertEqual(finish["answer"], "The conclusion differs [E1].")
        self.assertEqual(finish["cited"], ["E1"])
        self.assertAlmostEqual(finish["cost_usd"], 0.035)
        self.assertAlmostEqual(events[5]["cost_so_far_usd"], 0.03)
        json.dumps(events)  # all of it is plain JSON

    def test_watching_changes_nothing_the_model_sees(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            _, watched = self.run_with(RunLog(Path(folder) / f"w{LOG_SUFFIX}"))
        self.setUp()  # a fresh toolbox for the unwatched run
        _, unwatched = self.run_with(None)
        self.assertEqual(watched.requests, unwatched.requests)

    def test_a_stopped_audit_says_so_in_its_log(self) -> None:
        transport = ScriptedTransport(
            [self.SCRIPT[0], (402, b'{"error": {"message": "no credit"}}')]
        )
        client = OpenRouterClient(SETTINGS, transport=transport, sleep=lambda _: None)
        with tempfile.TemporaryDirectory() as folder:
            log = RunLog(Path(folder) / f"s{LOG_SUFFIX}")
            with self.assertRaises(AIProviderError):
                run_audit(client, self.box, "p", "Thing", (), log, {"title": "t"})
            events = read_events(log.path)
        self.assertEqual(events[-1]["kind"], "stopped")
        self.assertIn("AIProviderError", events[-1]["reason"])
        self.assertNotIn("finish", [e["kind"] for e in events])


if __name__ == "__main__":
    unittest.main()
