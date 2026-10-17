"""The AI helper's plumbing, with a scripted stand-in for OpenRouter (no network, no cost).

The scripted replies have the same shape as real OpenRouter replies (recorded from a live
run): an assistant message with `tool_calls`, then one with plain `content`.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from hekswerk_scry.ai.openrouter import AIProviderError, OpenRouterClient
from hekswerk_scry.ai.session import MAX_TOOL_ROUNDS, Session
from hekswerk_scry.ai.tools import Toolbox
from hekswerk_scry.core.enums import CheckKind
from hekswerk_scry.core.settings import AISettings, SettingsError, load_ai_settings
from hekswerk_scry.text_reports import render_turn
from tests.helpers import example

SETTINGS = AISettings(
    api_key="sk-or-test-secret",
    base_url="https://example.invalid/api/v1",
    model="anthropic/claude-opus-5.5",
    effort="high",
)


def tool_call(call_id: str, name: str, arguments: dict[str, Any] | str) -> dict[str, Any]:
    args = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}


def reply(message: dict[str, Any], cost: float = 0.01) -> tuple[int, bytes]:
    finish = "tool_calls" if message.get("tool_calls") else "stop"
    body = {
        "model": SETTINGS.model,
        "usage": {"cost": cost},
        "choices": [{"message": {"role": "assistant", **message}, "finish_reason": finish}],
    }
    return 200, json.dumps(body).encode()


class ScriptedTransport:
    """Hands out prepared replies in order and records every request."""

    def __init__(self, replies: list[tuple[int, bytes]]) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []

    def __call__(
        self, url: str, headers: dict[str, str], body: bytes, timeout: float
    ) -> tuple[int, bytes]:
        self.requests.append(json.loads(body))
        self.headers.append(headers)
        return self.replies.pop(0)


def session(replies: list[tuple[int, bytes]]) -> tuple[Session, ScriptedTransport]:
    transport = ScriptedTransport(replies)
    client = OpenRouterClient(SETTINGS, transport=transport, sleep=lambda _: None)
    return Session(client=client, toolbox=Toolbox(proof_map=example(), workspace=None)), transport


class TestClient(unittest.TestCase):
    def test_request_carries_model_tools_and_effort_and_never_forces_a_tool(self) -> None:
        sess, transport = session([reply({"content": "Hello."})])
        sess.ask("hi")
        body = transport.requests[0]
        self.assertEqual(body["model"], "anthropic/claude-opus-5.5")
        self.assertEqual(body["tool_choice"], "auto")
        self.assertEqual(body["reasoning"], {"effort": "high"})
        self.assertIn("list_steps", {t["function"]["name"] for t in body["tools"]})
        self.assertEqual(transport.headers[0]["Authorization"], "Bearer sk-or-test-secret")

    def test_busy_provider_is_retried_then_errors_are_plain(self) -> None:
        sess, transport = session([(429, b"{}"), reply({"content": "Done."})])
        self.assertEqual(sess.ask("hi").answer, "Done.")
        self.assertEqual(len(transport.requests), 2)
        sess, _ = session([(401, b'{"error": {"message": "No auth credentials found"}}')])
        with self.assertRaisesRegex(AIProviderError, "status 401.*No auth credentials"):
            sess.ask("hi")
        sess, _ = session([(200, b"<html>")])
        with self.assertRaisesRegex(AIProviderError, "isn't JSON"):
            sess.ask("hi")

    def test_the_key_is_never_shown(self) -> None:
        self.assertNotIn("secret", repr(SETTINGS))


class TestSettings(unittest.TestCase):
    def test_dotenv_environment_and_mistakes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, ".env").write_text(
                "# comment\nOPENROUTER_API_KEY='from-file'\nSCRY_EFFORT=medium\n", encoding="utf-8"
            )
            clean = {
                k: v
                for k, v in os.environ.items()
                if k not in ("OPENROUTER_API_KEY", "SCRY_MODEL", "SCRY_EFFORT")
            }
            with mock.patch.dict(os.environ, clean, clear=True):
                loaded = load_ai_settings(Path(folder))
                self.assertEqual((loaded.api_key, loaded.effort), ("from-file", "medium"))
                self.assertEqual(loaded.model, "anthropic/claude-opus-5.5")
            with mock.patch.dict(os.environ, {**clean, "SCRY_MODEL": "x/y"}, clear=True):
                self.assertEqual(load_ai_settings(Path(folder)).model, "x/y")
            with (
                mock.patch.dict(os.environ, {**clean, "SCRY_EFFORT": "huge"}, clear=True),
                self.assertRaisesRegex(SettingsError, "SCRY_EFFORT"),
            ):
                load_ai_settings(Path(folder))
            Path(folder, ".env").write_text("SCRY_EFFORT=high\n", encoding="utf-8")
            with (
                mock.patch.dict(os.environ, clean, clear=True),
                self.assertRaisesRegex(SettingsError, "OPENROUTER_API_KEY is not set"),
            ):
                load_ai_settings(Path(folder))


class TestSession(unittest.TestCase):
    def test_tool_results_become_cited_evidence(self) -> None:
        sess, transport = session(
            [
                reply(
                    {
                        "content": None,
                        "tool_calls": [
                            tool_call("t1", "scan_map", {}),
                            tool_call("t2", "read_step", {"step_id": "cube-split"}),
                        ],
                    }
                ),
                reply({"content": "The detour is a knot [E1, E2]."}, cost=0.02),
            ]
        )
        turn = sess.ask("where is the detour?")
        self.assertEqual([e.tool for e in turn.evidence], ["scan_map", "read_step"])
        self.assertEqual([e.evidence_id for e in turn.cited], ["E1", "E2"])
        self.assertIs(turn.cited[0].checked_by, CheckKind.WIRING)
        self.assertIsNone(turn.cited[1].checked_by)  # a lookup, not a check
        self.assertAlmostEqual(turn.cost_usd, 0.03)
        # The tool results went back to the model, labelled with their evidence IDs.
        tool_messages = [m for m in transport.requests[1]["messages"] if m["role"] == "tool"]
        self.assertTrue(tool_messages[0]["content"].startswith("[E1] "))
        self.assertEqual(tool_messages[1]["tool_call_id"], "t2")

    def test_history_is_append_only_and_keeps_the_models_messages_exactly(self) -> None:
        first = {
            "content": None,
            "reasoning_details": [{"type": "reasoning.encrypted", "data": "x"}],
            "tool_calls": [tool_call("t1", "list_steps", {})],
        }
        sess, transport = session([reply(first), reply({"content": "Done [E1]."})])
        sess.ask("list them")
        sent_first = transport.requests[0]["messages"]
        sent_second = transport.requests[1]["messages"]
        self.assertEqual(sent_second[: len(sent_first)], sent_first)
        self.assertEqual(sent_second[len(sent_first)], {"role": "assistant", **first})

    def test_citations_to_evidence_that_does_not_exist_are_flagged(self) -> None:
        sess, _ = session([reply({"content": "Lean proved it [E7]."})])
        turn = sess.ask("is it proven?")
        self.assertEqual(turn.unknown_citations, ["E7"])
        self.assertEqual(turn.checks_run, [])
        shown = render_turn(turn)
        self.assertIn("cites evidence that doesn't exist in this conversation: E7", shown)
        self.assertIn("No check was run this turn", shown)

    def test_checks_that_the_answer_ignores_are_pointed_out(self) -> None:
        sess, _ = session(
            [
                reply({"content": None, "tool_calls": [tool_call("t1", "scan_map", {})]}),
                reply({"content": "Looks fine to me."}),
            ]
        )
        shown = render_turn(sess.ask("ok?"))
        self.assertIn("but the answer cites none of them", shown)
        self.assertTrue(shown.startswith("AI's reading:"))

    def test_bad_tool_input_is_reported_back_to_the_model_not_raised(self) -> None:
        sess, transport = session(
            [
                reply(
                    {
                        "content": None,
                        "tool_calls": [
                            tool_call("t1", "read_step", "{not json"),
                            tool_call("t2", "read_step", {"step_id": "ghost"}),
                            tool_call("t3", "try_new_proof", {"step_id": "x"}),
                        ],
                    }
                ),
                reply({"content": "Sorry."}),
            ]
        )
        turn = sess.ask("go")
        tool_messages = [
            m["content"] for m in transport.requests[1]["messages"] if m["role"] == "tool"
        ]
        self.assertIn("Couldn't read the tool arguments", tool_messages[0])
        self.assertIn("no step 'ghost'", tool_messages[1])
        # Without Lean, Lean tools aren't offered, and asking for one is refused.
        self.assertIn("There is no tool called 'try_new_proof'", tool_messages[2])
        self.assertEqual(len(turn.evidence), 2)

    def test_a_turn_that_never_answers_stops_at_the_limit(self) -> None:
        loop = reply({"content": None, "tool_calls": [tool_call("t", "list_steps", {})]})
        sess, transport = session([loop] * MAX_TOOL_ROUNDS)
        turn = sess.ask("go")
        self.assertTrue(turn.hit_round_limit)
        self.assertEqual(len(transport.requests), MAX_TOOL_ROUNDS)


class TestToolbox(unittest.TestCase):
    def test_lean_tools_are_offered_only_with_lean(self) -> None:
        names = {t["function"]["name"] for t in Toolbox(example(), None).definitions()}
        self.assertEqual(names, {"list_steps", "read_step", "scan_map"})


if __name__ == "__main__":
    unittest.main()
