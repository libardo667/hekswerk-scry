# Decision 0007: The browser workbench, read-only first

**Status:** accepted for Checkpoint 6.

## The problem

Everything Scry did happened in a terminal, so only the person running it could follow an
audit, and only by reading its final report. The owner asked for a way to "actually sort of
follow along with what's being done".

## Decisions

**Watch first; act later.** `scry serve` shows audits as they run, benchmark results,
audit reports and proof maps. It starts nothing, spends nothing and writes nothing. Running
audits, drafting cards and applying them from the browser can come once watching is solid.

**Every audit keeps an append-only run log** (`ai/run_log.py`, `*.events.jsonl`): what it is
about (`start`, including the statement it audits), what the model said between tool calls,
each piece of evidence in full, each comparison row, and how it ended (`finish` or
`stopped`). Each event is one line, written whole and flushed at once, so the page can follow
a run while it happens and a crash or restart loses at most the event being written.
Watching changes nothing the model sees; a test sends the same scripted run with and without
a log and requires identical requests.

**Who said what, on screen.** Evidence is labelled with who produced it ("Lean (checks the
math itself)", "lookup (no check)"). The helper's words and rows are labelled "AI's
reading". Citations such as `[E9]` open the evidence they name. Lean's accepted and rejected
claims are marked, and each row lights up the Lean lines it is about. In a benchmark copy the
planted lines are marked for the person, who can see them; the helper never could.

**Built the way Parallax is**, the owner's research workspace: plain JavaScript modules with
no build step, and a small local server (here, Python's standard library). Nothing from a run
log, paper or model reply is ever treated as HTML: text goes in through `textContent`, and a
small Markdown renderer builds DOM nodes. Parallax's 3D map doesn't carry over; a proof map is
drawn flat, each step below the steps it takes facts from.

**Safety.** The server listens on 127.0.0.1 only and refuses requests whose `Host` header
names any other site (so a web page elsewhere can't reach it through DNS rebinding). Files
are named by tokens that must resolve, inside a folder it was given, to a file of the kind the
request asks for. Pages are served with a Content-Security-Policy that allows only the
workbench's own scripts and styles. Tests run a real server and check each refusal, and the
mutation check confirms they would notice each safeguard going missing.

## Not yet

- Starting work from the browser (audits, benchmarks, Lean checks, cards).
- Showing the exact passage the helper quoted from a paper lookup, next to its citation.
- Audits from before run logs existed (the first benchmark) show their written report only.
