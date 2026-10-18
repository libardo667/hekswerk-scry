# Decision 0005: Checking what a formal statement says

**Status:** accepted for Checkpoint 5.

## The problem

Lean's check of a proof settles the *formal statement*, and nothing more. A formal
statement can differ from the published claim while every proof of it is correct: it can
assume more, conclude less, cover only a special case, or rest on definitions that mean
something other than the paper's words. The owner put it this way: a valid formal proof is
not necessarily a proof of the claim a human thinks it establishes.

OpenAI's mathematics repository (`openai/math`, Lean v4.34.1, Apache-2.0) already splits
the question in two. Each formalized result has a *comparator challenge*: a short Lean file
stating it, checked by Lean's `comparator` tool against the module that proves it. That
settles "does the proof prove this statement". Nothing settles "does this statement say what
the paper claims"; OpenAI covers it with a hand-written scope note per paper. Scry works on
that second question.

## Decisions

**Lean says what Lean can.** `scry lean-statement` (exporter `--statement` mode) reports a
theorem's hypotheses, conclusion, and every *project-specific* definition it relies on, with
bodies and source lines, followed through definitions up to a limit. Definitions from Lean,
Std and Mathlib are trusted vocabulary; the project's own definitions are where meaning can
drift, so each one is listed for a person to read.

**Two probes, judged by the kernel.**
- *Vacuity*: the hypotheses contradict each other, so the theorem says nothing.
- *Triviality*: the conclusion follows without the hypotheses, so they aren't needed or the
  conclusion is weaker than it looks.

A short list of standard tactics is tried, each with a fixed amount of work (heartbeats). A
probe counts as found only when the Lean kernel accepts the resulting proof as a
declaration. When the tactics find nothing, the report says exactly that and never treats
it as evidence that the statement is sound. For the triviality probe, the hypotheses are
removed from the context so the tactics cannot use them; an early version left them in, and
`positivity` failed on a goal it proves instantly.

**The AI lines statement and paper up, and labels it.** `scry audit-statement` gives the AI
helper Lean's reading of the statement, the definitions, and the paper's LaTeX (fetched on
demand). It compares the two point by point (quantifiers, domains, strictness, constants,
conclusion), and can write small Lean claims of its own, such as a special case the paper
says the result covers, which Lean checks against the real proof. The report is the helper's
reading except where it cites a Lean check.

**The answer key stays sealed.** The helper never sees OpenAI's scope notes. Each saved audit
puts the note next to the helper's report so a person can judge it. Only the note's links
(which paper folders belong to a challenge) are read.

## Lean v4.34.1

Proof files live in their own Lake projects; Scry keeps one exporter build per supported Lean
version (`lean/` for v4.10.0-rc2, `lean-exporters/v4.34.1/`). The exporter imports only Lean,
so one build serves every project on that version. Porting it took API renames only
(`String.Pos.Raw`, `Std.HashMap`, `Std.TreeSet`-based `MVarIdSet`, `Substring.Raw`). A test
exports the same proof under both versions, against Mathlibs two years apart, and requires
identical maps.

## Coverage

390 of `openai/math`'s 416 comparator challenges need only Mathlib and OpenAI's own files.
The rest also depend on outside libraries (the prime number theorem projects, Rellich–
Kondrachov, and others). Lean loads all of Mathlib for most files, so each statement read
takes a few minutes; results are stored, keyed by everything that could change them.

## First result

The first live audit, of `TruffetCounterexample`, is in
[`docs/examples/truffet-statement-audit.md`](../examples/truffet-statement-audit.md), next to
OpenAI's scope note. The scope note says only that the formalization "checks that a
specified two-step execution of Truffet's elimination procedure terminates with a feasible
but nonoptimal output". The helper reached the same reading on its own and went further:

- It found two places where Lean *concludes less* than the paper: the paper says the true
  minimum is exactly zero and that the first substitution already removes every optimum,
  while the theorem only exhibits one better point. It then had Lean prove both claims
  against the real definitions (two checks accepted).
- It found one paper claim that is *not in the formalization* (the search endpoints μ = 0,
  λ = −4 and Eq. 23b).
- It named the real limit of any audit here: the procedure itself is the formalizer's
  reconstruction of Truffet's rule, and whether it matches Truffet's own paper (not in the
  repository) can't be checked.

One of its four Lean checks failed on its own tactics, and it said so instead of counting it
against the claim. The audit cost $0.51 and took 28 minutes, most of it Lean loading Mathlib
for each check. One audit is an anecdote, not a benchmark; scoring audits against scope notes
across several papers is the next step.

The statement reader also runs on Lean v4.10 (AlphaProof's IMO statements). Helpers Lean
generates by itself, such as the pattern-matching function behind `{(a, b) | ...}`, are left
off the list of definitions to read: nobody wrote them.

## Measuring audits: the planted-difference benchmark

An audit that has never missed a planted error hasn't been measured. `scry
statement-benchmark` works like the mutation check: it plants known differences into copies
of real comparator statements (`benchmarks/statement-plants.json`), audits each copy and an
unchanged one blind, and scores them from the rows the helper records with `record_verdict`.
Copies share a name, sit in folders with meaningless names, and get identical instructions
and tools; a test checks the helper can't tell them apart. The helper's Lean claims are
checked against the copy's own definitions, so a planted definition shows up in Lean too. A
plant is *caught* when a row other than "matches" points at its lines, a *dangerous miss*
when only a "matches" row does, and *missed* otherwise.

The first run is in [`docs/examples/statement-benchmark-1.md`](../examples/statement-benchmark-1.md):
six plants in three statements (FiniteCongruenceGraph, FourRowPermanent, PlaneColoring),
**six caught, no dangerous misses**, nine audits for $8.77. Five of the six plants weaken a
proven statement, so a proof of the planted version exists: Lean alone could never catch them.

- The subtlest plants were pinned to their exact lines: one flipped `≤` inside a
  definition three steps from the theorem, and `p₀ < 2` loosened to `p₀ ≤ 2`.
- On the plant that dropped the norm's 1/4 normalization, the helper had Lean prove the
  whole planted theorem in about twenty lines, with the total-variation and marginal
  hypotheses unused. That is Lean-checked evidence that the statement had become trivial,
  far stronger than a reading. Lean's own triviality probe couldn't see it, because the
  theorem has no hypotheses of its own (they sit inside `∃ p₀, ...`).
- The unchanged copies agreed with OpenAI's scope notes. PlaneColoring's flagged that it
  proves only the classical upper bound of seven, not the paper's main claim (no
  five-colouring). That is correct for this statement alone; OpenAI states the main claim
  in a separate challenge, which the helper had no way to know about.

What this does **not** show yet:

- Six plants, one model, one run each. Nothing about how much results vary between runs.
- The plants were written by the same model family that audits them, so they may be
  exactly the errors it is good at seeing. Plants from people, or real misformalizations
  found in the past, are the stronger test.
- A row may cover up to 25 lines, so a broad row can catch a plant without pinning it;
  in this run every catching row was narrow, but the rule allows less.

Follow-ups: tell an audit which of the paper's other results are stated in sibling
challenges (from the scope note's links, which are already read, never its text); a
triviality probe that looks inside a leading `∃`; tighter row spans; plants not written by
the auditor; repeated runs.
