# Audits of 2026-10-19, re-run after the outside review

Run on commit `c037950` (the fixes in [decision 0009](../../../decisions/0009-evidence-identity.md)),
with `anthropic/claude-opus-5.5` at effort high. Each `.events.jsonl` file is the complete run
log: the setup it ran under (by content: model, instructions, tools and their code, the
statement and every Lean input, each paper file), every tool call and its result, each Lean
claim the helper wrote with Lean's verdict and receipt, every comparison row, and the cost.
The `.md` files are the reports, next to OpenAI's scope note. `scry serve --runs
docs/examples/runs` shows them.

Statements, paper excerpts and scope notes come from OpenAI's mathematics repository
(https://github.com/openai/math), used under its Apache-2.0 license.

## `truffet/`: TruffetCounterexample, again ($0.69)

A new run, not a replay: the first audit (2026-10-17) kept no run log, and its two papers'
files were read through names they share, so it may have read the wrong paper's introduction.
This run read both papers by unambiguous names, and was told what Scry checked: Lean, run
here, accepts the solution module's theorem with only the standard axioms (that the solution
states exactly this file's statement was not checked).

It reached the first audit's reading: the instance and both forced steps match the paper; the
theorem exhibits a better point but does not state that the minimum is exactly 0, and the
helper had Lean prove the missing lower bound (accepted); the search endpoints are not in the
formalization; whether the modelled rule is Truffet's own can't be checked from these sources.
Unlike the first run, it left "the first substitution removes every optimum" as not in the
formalization, without a Lean check.

## `benchmark-2/`: FourRowPermanent's three copies ($2.01)

A new run of the copies whose first audits could read only one paper's copy of file names the
challenge's ten papers share. Every audit here read the four-row permanent paper's own
introduction.

- **control**: nothing flagged.
- **exponent-two-allowed**: *conflicting*. The row "Range of the exponent p0" says Lean
  concludes less, at the planted line; two "matches" rows about other items (quantifier order,
  the conclusion) cover it too.
- **unnormalized-norm**: *caught* ("L^p norm normalization": differs).

Same scores as the first run, re-scored under the same rule; two more audits, one model, one
try each.
