"""A conversation between a person and the AI helper about one proof map.

Each turn, the model may call tools any number of times (up to a limit) before it
answers. Its answer is always shown as "AI's reading": a claim, not a check. Scry then
looks at which evidence the answer cites ([E3] and so on) and reports, in plain words:

- which checks the answer rests on, and which checker produced each;
- citations to evidence that doesn't exist in this conversation;
- when no check was run this turn at all.

These are statements about the conversation's own record, not judgements of the math.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from hekswerk_scry.ai.openrouter import AIProviderError, OpenRouterClient
from hekswerk_scry.ai.tools import Evidence, Toolbox, ToolRunner

MAX_TOOL_ROUNDS = 16
# A citation is a bracket holding one or more evidence IDs: [E3] or [E4, E5].
_CITATION = re.compile(r"\[\s*(E\d+(?:\s*,\s*E\d+)*)\s*\]")

SYSTEM_PROMPT = """\
You are the AI helper in Scry, a workbench for untangling convoluted, machine-written \
mathematical proofs into steps a person can follow. You work together with the person: \
the goal is a proof that is both correct and understandable. Lean decides what is correct.

How you work:
- Find things out with your tools before you say them. Each tool result is evidence with \
an ID like E3. Cite the evidence each claim rests on, in square brackets: [E3].
- Never say a step or proof is correct, proven, needed or unneeded unless a Lean check in \
this conversation says so, and cite it. Without one, say it is your reading and not checked.
- When the person offers a hunch ("isn't this just a triangle inequality?", "this step \
looks pointless"), test it with a Lean check before agreeing. If the check contradicts \
them, say so plainly and show the evidence. Agreeing without checking is not helping.
- When you propose a simpler proof, draft it with try_new_proof so Lean judges it. Write \
Lean a person can follow: one idea per line where you can, a short `--` comment saying \
why each step holds, and well-known lemmas or tactics over opaque automation when the \
choice is close. Lean's verdict on correctness is final; readability is a judgement the \
person makes with you.
- If a card is rejected, read Lean's errors and try again or explain what blocks it.
- Only the person can apply a card. Tell them the card ID when one is ready.
- Use plain technical English: a sharp adult who isn't a specialist should follow you. \
Be concise.

The proof map you are working on:
{overview}
"""


@dataclass
class Turn:
    """What happened in one turn: the answer, and what it rests on."""

    answer: str
    evidence: list[Evidence]
    cited: list[Evidence]
    unknown_citations: list[str]
    cost_usd: float
    hit_round_limit: bool = False

    @property
    def checks_run(self) -> list[Evidence]:
        return [e for e in self.evidence if e.checked_by is not None]


@dataclass
class Session:
    """A conversation with the model. `system_prompt` defaults to the proof helper's
    instructions (which need a proof-map `Toolbox`); other uses pass their own."""

    client: OpenRouterClient
    toolbox: ToolRunner
    system_prompt: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    total_cost_usd: float = 0.0

    def __post_init__(self) -> None:
        if not self.system_prompt:
            if not isinstance(self.toolbox, Toolbox):
                raise TypeError("A session with a custom toolbox needs its own system prompt.")
            self.system_prompt = SYSTEM_PROMPT.format(overview=_overview(self.toolbox))
        if not self.messages:
            self.messages.append({"role": "system", "content": self.system_prompt})

    def ask(self, text: str) -> Turn:
        """Send the person's message; run the model's tool calls; return its answer."""
        self.messages.append({"role": "user", "content": text})
        first_evidence = len(self.toolbox.evidence)
        cost = 0.0
        tools = self.toolbox.definitions()
        for _ in range(MAX_TOOL_ROUNDS):
            reply = self.client.chat(self.messages, tools)
            cost += reply.cost_usd or 0.0
            # Keep the model's message exactly as returned: history is append-only.
            self.messages.append(reply.message)
            if not reply.tool_calls:
                return self._finish(reply.text, first_evidence, cost)
            for call in reply.tool_calls:
                function = call.get("function") or {}
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                    if not isinstance(arguments, dict):
                        raise ValueError("arguments are not an object")
                except (json.JSONDecodeError, ValueError) as exc:
                    content = (
                        f"Couldn't read the tool arguments ({exc}); send them as a JSON object."
                    )
                else:
                    evidence = self.toolbox.run(str(function.get("name", "")), arguments)
                    content = f"[{evidence.evidence_id}] {evidence.result}"
                self.messages.append(
                    {"role": "tool", "tool_call_id": call.get("id", ""), "content": content}
                )
        turn = self._finish("(The helper used its whole budget of tool calls for this turn "
                            "without answering. Ask it to summarise what it found.)",
                            first_evidence, cost)
        turn.hit_round_limit = True
        return turn

    def _finish(self, answer: str, first_evidence: int, cost: float) -> Turn:
        self.total_cost_usd += cost
        by_id = {e.evidence_id: e for e in self.toolbox.evidence}
        cited_ids = list(dict.fromkeys(
            evidence_id.strip()
            for group in _CITATION.findall(answer)
            for evidence_id in group.split(",")
        ))
        return Turn(
            answer=answer.strip(),
            evidence=self.toolbox.evidence[first_evidence:],
            cited=[by_id[i] for i in cited_ids if i in by_id],
            unknown_citations=[i for i in cited_ids if i not in by_id],
            cost_usd=cost,
        )


def _overview(toolbox: Toolbox) -> str:
    proof_map = toolbox.proof_map
    lines = [
        f"Title: {proof_map.title}",
        f"Goal: {proof_map.goal}",
        f"Starting facts: {', '.join(proof_map.starting_facts) or '(none)'}",
        f"Steps: {len(proof_map.steps)} (use list_steps to see them)",
        "Lean is available: you can run Lean checks and draft cards."
        if toolbox.workspace is not None and proof_map.lean_source is not None
        else "Lean is not available for this map: only wiring checks can be run.",
    ]
    return "\n".join(lines)


__all__ = ["MAX_TOOL_ROUNDS", "SYSTEM_PROMPT", "AIProviderError", "Session", "Turn"]
