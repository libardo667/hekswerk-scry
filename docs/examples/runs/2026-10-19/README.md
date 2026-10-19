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

## Every benchmark score so far

Six differences planted in copies of three statements. The first run is
[`statement-benchmark-1.md`](../../statement-benchmark-1.md) (2026-10-18, $8.77, re-scored
under the current rule from its saved rows). The re-run is [`benchmark-2/`](benchmark-2/summary.md)
(2026-10-19, $2.01), only for the copies whose first audits could have read the wrong paper.

| Statement | Plant | 2026-10-18 | 2026-10-19 |
| --- | --- | --- | --- |
| FiniteCongruenceGraph | one-direction | conflicting | not re-run |
| FiniteCongruenceGraph | placement-reversed | caught | not re-run |
| FourRowPermanent | exponent-two-allowed | conflicting | [conflicting](benchmark-2/FourRowPermanent--exponent-two-allowed.md) |
| FourRowPermanent | unnormalized-norm | caught | [caught](benchmark-2/FourRowPermanent--unnormalized-norm.md) |
| PlaneColoring | line-not-plane | caught | not re-run |
| PlaneColoring | bounded-region | conflicting | not re-run |
| **Total** | | 3 caught, 3 conflicting | 1 caught, 1 conflicting |

No plant was a dangerous miss, unresolved or missed. The unchanged copies:
FiniteCongruenceGraph, one item flagged as not in the formalization; FourRowPermanent,
nothing flagged, in both runs ([control](benchmark-2/FourRowPermanent--control.md));
PlaneColoring, two items flagged.

Scores are per line, so a "conflicting" score can't tell two items on the same line apart.
In every conflicting case a row names the planted difference, and a "matches" row about
another item covers the same line. In exponent-two-allowed, for example, line 38 is
`∃ p₀ : ℝ, 4 / 3 < p₀ ∧ p₀ ≤ 2 ∧`. That one line holds the planted bound, which row 1 flags,
and the quantifier whose order row 2 says matches. Telling those apart is for a person reading
the rows.

The strongest single piece of evidence is in the unnormalized-norm copy: **E15**, receipt
`sha256:c32d8a23a5e85afb` ([report](benchmark-2/FourRowPermanent--unnormalized-norm.md),
[run log, line 31](benchmark-2/FourRowPermanent--unnormalized-norm-20261019-151146.events.jsonl#L31)).
Lean accepted a proof of the copy's theorem, written out again in the claim, with p₀ = 3/2 and
ε = 1. The proof never uses the total-variation or uniform-marginal hypotheses. Without the
paper's 1/4, the planted statement holds for every probability law.

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
