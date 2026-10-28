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
under the current rule from its saved rows). The second run is [`benchmark-2/`](benchmark-2/summary.md)
($5.75 across all nine copies: `FourRowPermanent` ran 2026-10-19 for $2.01 and was reused by setup
hash on 2026-10-28 when `FiniteCongruenceGraph` and `PlaneColoring` ran for $3.74), with full
`.events.jsonl` run logs and unambiguous paper paths for every copy.

| Statement | Plant | 2026-10-18 | benchmark-2 (2026-10-19 / 2026-10-28) |
| --- | --- | --- | --- |
| FiniteCongruenceGraph | one-direction | conflicting | [conflicting](benchmark-2/FiniteCongruenceGraph--one-direction.md) |
| FiniteCongruenceGraph | placement-reversed | caught | [caught](benchmark-2/FiniteCongruenceGraph--placement-reversed.md) |
| FourRowPermanent | exponent-two-allowed | conflicting | [conflicting](benchmark-2/FourRowPermanent--exponent-two-allowed.md) |
| FourRowPermanent | unnormalized-norm | caught | [caught](benchmark-2/FourRowPermanent--unnormalized-norm.md) |
| PlaneColoring | line-not-plane | caught | [caught](benchmark-2/PlaneColoring--line-not-plane.md) |
| PlaneColoring | bounded-region | conflicting | [conflicting](benchmark-2/PlaneColoring--bounded-region.md) |
| **Total** | | 3 caught, 3 conflicting | 3 caught, 3 conflicting |

No plant was a dangerous miss, unresolved or missed. The unchanged copies:
FiniteCongruenceGraph, one item flagged as not in the formalization
([control](benchmark-2/FiniteCongruenceGraph--control.md)); FourRowPermanent,
nothing flagged, in both runs ([control](benchmark-2/FourRowPermanent--control.md));
PlaneColoring, two items flagged in the first run and one (`χ ≥ 6` not in the formalization)
in the second ([control](benchmark-2/PlaneColoring--control.md)).

Scores are per line, so a "conflicting" score can't tell two items on the same line apart.
In every conflicting case a row names the planted difference, and a "matches" row about
another item covers the same line. In exponent-two-allowed, for example, line 38 is
`∃ p₀ : ℝ, 4 / 3 < p₀ ∧ p₀ ≤ 2 ∧`. That one line holds the planted bound, which row 1 flags,
and the quantifier whose order row 2 says matches. Telling those apart is for a person reading
the rows.

In all three `caught` copies, the helper backed its finding with a proof Lean's kernel accepted:

- **`FourRowPermanent--unnormalized-norm`:** **E15**, receipt
  `sha256:c32d8a23a5e85afb` ([report](benchmark-2/FourRowPermanent--unnormalized-norm.md),
  [run log, line 31](benchmark-2/FourRowPermanent--unnormalized-norm-20261019-151146.events.jsonl#L31)).
  Lean accepted a proof of the copy's theorem, written out again in the claim, with p₀ = 3/2 and
  ε = 1. The proof never uses the total-variation or uniform-marginal hypotheses. Without the
  paper's 1/4, the planted statement holds for every probability law.
- **`PlaneColoring--line-not-plane`:** **E9**, receipt `sha256:7f243c8275422198`
  ([run log, line 16](benchmark-2/PlaneColoring--line-not-plane-20261028-171218.events.jsonl#L16)),
  and **E11**, receipt `sha256:fe6670453096b96d`
  ([report](benchmark-2/PlaneColoring--line-not-plane.md),
  [run log, line 19](benchmark-2/PlaneColoring--line-not-plane-20261028-171218.events.jsonl#L19)).
  Lean proved `Module.finrank ℝ OAI.Problem160.Plane = 1` and proved `OAI.Problem160.ProperColoring 2`
  on that space by parity of ⌊x₀⌋, showing the 7-colouring theorem is trivial on ℝ¹.
- **`FiniteCongruenceGraph--placement-reversed`:** **E16**, receipt `sha256:dfb28dcc0ed63159`
  ([run log, line 30](benchmark-2/FiniteCongruenceGraph--placement-reversed-20261028-170703.events.jsonl#L30)),
  and **E15**, receipt `sha256:047cc5ac04390c59`
  ([report](benchmark-2/FiniteCongruenceGraph--placement-reversed.md),
  [run log, line 28](benchmark-2/FiniteCongruenceGraph--placement-reversed-20261028-170703.events.jsonl#L28)).
  Lean proved that reversing the inequality in `Admissible` forces every admissible map to be
  injective, and proved that a concrete 4-vertex colouring satisfying the paper's label-decreasing
  condition is `¬ OAI.FiniteCongruence.IsGraphWitness`.

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

## `benchmark-2/`: all nine copies ($5.75)

A full run of all nine copies under the unambiguous paper-path layout and setup-hash evidence
rules. `FourRowPermanent`'s three copies ran on 2026-10-19 ($2.01) and were reused by setup hash
when `FiniteCongruenceGraph` and `PlaneColoring` ran on 2026-10-28 ($3.74).

- **`FiniteCongruenceGraph`**: **control** flagged only the paper's finite-check remark as not in
  the formalization; **one-direction** scored *conflicting* ("Direction of the theorem (iff vs one
  direction)": Lean concludes less, sharing lines 57–58 with a "matches" row on the lattice
  hypotheses); **placement-reversed** scored *caught* ("Admissible placement (direction of
  inequality)": differs, backed by Lean proofs E15 and E16).
- **`FourRowPermanent`**: **control** flagged nothing; **exponent-two-allowed** scored
  *conflicting* ("Range of the exponent p0": Lean concludes less, sharing line 38 with two
  "matches" rows); **unnormalized-norm** scored *caught* ("L^p norm normalization": differs,
  backed by Lean proof E15).
- **`PlaneColoring`**: **control** flagged the paper's main claim (`χ ≥ 6`, no proper
  five-colouring) as not in the formalization, matching OpenAI's scope note `158.md`;
  **line-not-plane** scored *caught* ("Ambient space ("Plane")": differs, backed by Lean proofs
  E9 and E11); **bounded-region** scored *conflicting* ("Domain of coloring constraint (upper
  bound χ ≤ 7)": Lean concludes less, sharing lines 23–25 with a "matches" row on the number of
  colours).

Same scores as the first run across all six plants; now every copy has a full `.events.jsonl`
run log and receipted Lean checks.
