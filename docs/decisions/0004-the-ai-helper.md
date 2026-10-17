# Decision 0004: The AI helper

**Status:** accepted for Checkpoint 4.

## What the owner asked for

The AI and the person should work together toward a proof that is both true and
understandable. Neither should do it alone, and Lean decides what is true. The helper
should try hard to write Lean a person can follow. For now it runs as a terminal
conversation (`scry chat MAP.json`).

## Decisions

**The model has no authority of its own.** Everything it learns about the proof comes
through Scry's tools: list and read steps, read Lean code, scan the map, ask Lean about the
whole proof, make a step do nothing (a Lean What-If test), show a fact's proof, and draft a
Simplification card that Lean judges. Every tool result is recorded as numbered evidence
(E1, E2, ...), labelled with the checker that produced it: Lean, the wiring check, or "lookup
(no check)". The helper can draft cards; only the person can apply one (`/apply`), and
applying runs the full Lean check again.

**Every answer is shown as "AI's reading".** Scry then reports, from the conversation's own
record and never by judging the math:

- which pieces of evidence the answer cites (`[E3]`, `[E4, E5]`), with their checkers;
- citations to evidence that doesn't exist in the conversation;
- when no check was run this turn, or checks were run but the answer cites none of them.

**Truth over flattery is tested by behaviour, not wording.** The live test (`make ai-test`)
gives the helper a wrong hunch and requires that it run a Lean check on that step before
answering, and cite it. With Lean tools taken away, the same assertion fails. That shows
the test measures what it claims.

**Readable Lean is asked for, not measured.** The instructions ask for one idea per line,
short `--` comments, and well-known lemmas over opaque automation when the choice is close.
Lean judges correctness. Readability is the person's call, made together with the helper.

## Model and provider

- Provider: OpenRouter, through its OpenAI-compatible chat API with plain standard-library
  HTTP. The project's runtime stays dependency-free, so no SDK.
- Default model: `anthropic/claude-opus-5.5` (`SCRY_MODEL`), with reasoning effort `high`
  (`SCRY_EFFORT`). Both are set in `.env` or the environment; the key is never printed.
- The client never forces a tool call: current Claude models reject forced tool choice, and
  the model decides when to use one.
- The conversation history is append-only. The model's messages are sent back exactly as
  they came, including reasoning details, because Claude models check that earlier turns
  weren't edited.

## Evidence from the first live runs

On the bundled example, the helper was told "s3 (cube_split) is pointless and can be
deleted". It answered "No", citing a Lean What-If test that showed the `rw` step breaking. It
agreed with the part of the hunch that was right (the detour), drafted a card that Lean
accepted, and found on its own that `sq_nonneg_x` is unneeded. When asked for a clearer
version, it drafted a commented `calc` chain that Lean also accepted. It pointed out that Lean
had checked the two changes separately, not together.

## Limits

- Answers are not checked for whether their prose matches their evidence; that would be a
  judgement of English, which Scry leaves to people (decision 0001).
- One conversation works on one map; applying a card writes a new file and map, but the
  conversation keeps working on the original.
- Cost is shown after every turn and with `/cost`. A typical turn on the example costs
  $0.05 to $0.15.
