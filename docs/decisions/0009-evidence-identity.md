# Decision 0009: Evidence that says exactly what was checked, against what

**Status:** accepted, after the outside review of 2026-10-19.

## The problem

An outside review of the Checkpoint 6 code found eight places where Scry's labels claimed
more than the code had checked. None was Lean proving something false. Each was Scry passing
on a judgement that its evidence didn't support. They fall into two classes.

**A label stronger than its check.**
- A fresh Lean run that printed a passing-looking message and then *failed* (exit code 23,
  or killed) was labelled Lean-checked: the judgement read Lean's messages and never the way
  the process ended.
- A probe "found" a contradiction among a statement's hypotheses with a proof that rested on
  `sorryAx`, through a lemma left as `sorry`. Lean's kernel accepted it, but a proof from
  `sorry` shows nothing. This was shown end to end with the old exporter on
  `tests/fixtures/lean/UntrustedProbe.lean`.
- The audit prompt told the AI helper "Lean has checked a proof of it" for every comparator
  challenge. Nothing had checked anything; the repository says a solution exists.
- The benchmark counted an "unclear" row as catching a plant, and let it hide a "matches"
  row on the same lines.

**Evidence that outlived its inputs, or pointed at the wrong one.**
- A stored statement reading was keyed by the theorem's file alone. Changing a definition in
  a file it imports, or a package, reused the old reading.
- Two papers' `build/main.tex` were both called `main.tex`, and reading one gave the other.
  Real audits were affected: the Truffet audit's two papers share five such names, and the
  FourRowPermanent audits' ten papers share six; one of those audits asked for
  `sections/01-introduction.tex` and was given another paper's introduction.
- The browser computed an outline's changed-files warning once, then kept it while the
  outline file was unchanged, however the Lean files changed.
- The benchmark reused an earlier audit whenever the copied statement was byte-identical:
  a different model, instructions, tools, paper or imported definition didn't count, and an
  audit that had stopped at its round limit was reused as if finished.

## Decisions

**A pass needs a clean ending.** `judge` takes the run's exit code; a run that didn't end
with code 0 proves nothing, whatever it printed. `Receipt` itself refuses to say a Lean
check passed unless its run ended normally and in time, so no caller can get this wrong.

**A probe counts only on the standard axioms.** The exporter collects every axiom a probe's
proof rests on, through every lemma it uses. A proof that needs more than propext,
Classical.choice and Quot.sound is reported apart (`untrusted`, with its tactic and axioms),
and the search goes on for one that doesn't. `ProbeOutcome` refuses a report that counts such
a proof as found. Tools and reports show the axioms.

**The helper is told what Scry checked, and no more.** Before an audit spends anything,
`check_solution` runs Lean on the solution module's theorems in this checkout. The prompt then
says one of: Lean here accepts them with no `sorry` and only standard axioms, *and Scry has
not checked that the solution states exactly what the challenge file states* (upstream's
`comparator` does that); or Lean here didn't accept them, and why; or the solution isn't in
the checkout. The status, and the receipts it rests on, go in the run log and the report.

**One description of a reading's inputs.** `LeanWorkspace.inputs(path)` is everything
besides Lean and Scry that Lean's answer about a file depends on, by content: the file, every
project file it imports (directly or not), the Lake setup files, and each package as checked
out (a git package by its commit, a local one by its Lean files). Stored statement readings
are keyed by it. A stored reading is only reused when every input is identical, so it can't
describe code that has since changed; there is nothing to rebuild before reusing it.

**One name per paper file.** When an audit has more than one paper, every file's name starts
with its paper's folder (`Randomized-...-games/source/main.tex`). Names that would still be the
same are refused when the toolbox is made. The run log records each file's SHA-256.

**Freshness is computed when it's asked for.** The browser keeps an outline's index while
the outline file is unchanged, and compares its Lean files afresh on every request.

**A benchmark score says where an audit pointed, honestly.** Five outcomes, from the rows at
the planted lines: *caught* (a row names a difference, none says "matches"), *conflicting*
(both), *dangerous miss* ("matches", no difference; "unclear" can't hide it), *unresolved*
(only "unclear"), *missed* (no row). The browser scores saved rows again under the current
rule and shows the saved score beside it when they differ. Re-scored, the first benchmark run
is 3 caught and 3 conflicting, not 6 caught. In all three conflicting cases the "matches" row is
about another item on overlapping lines, which a person would read as a catch. That reading
is a person's job; the score doesn't pretend to do it.

**An audit is reused only for the same experiment.** Each audit's *setup* is recorded:
model, effort and provider; the instructions, the tools and the source of the code behind
them; the copy and every Lean input of its reading; the Lean readings' receipts; and each
paper file, by content (`audit_setup`). A later run reuses an audit only when the setup is
identical and the audit finished. The summary says which audits were reused, from when, and
which stopped at the round limit. Results saved before setups were recorded can still be read,
but nothing in them is reused.

**What a statement report leaves out, it says.** The exporter prints up to 400 project
definitions and counts the rest (`definitions_total`); the report and the helper's tools say
when the list is cut off. Definition bodies are no longer clipped at 3,000 characters;
`read_definition` returns a long body in pages, and says where the next page starts.

## Not done yet

- **Statement identity with the solution.** Scry checks the solution's proofs, not that they
  prove exactly the challenge's statement. Running upstream's `comparator` (which needs
  `landrun` and `lean4export`) would settle it.
- **A person's verdict on each catch.** Scores are mechanical; nothing yet records a
  person's judgement of whether a catching row names the planted change.
- **A replayable Truffet audit.** The first Truffet audit predates run logs, and it may have
  read the wrong paper's introduction. Its supplementary Lean checks exist only as the
  report's summary. A new run would record everything above; it would be a new run, not a
  replay of the old one.
- **Sibling challenges.** An audit isn't told which of the paper's other results are stated
  in other challenges, so it can report a result as missing that another challenge states.
