<!-- First run of `scry statement-benchmark` (2026-10-18), commits 7d9c433..df69967, model anthropic/claude-opus-5.5 at effort high. Statements and paper material come from OpenAI's mathematics repository (https://github.com/openai/math), used under its Apache-2.0 license. -->

# Statement audit benchmark

6 planted differences in 3 statements: 6 caught, 0 dangerous misses (a row said "matches" over the planted lines), 0 missed. Total cost $8.77 (6 audits reused from an earlier run).

Scored mechanically from the rows each audit recorded. The audits are the AI helper's reading; the scores only say whether a row pointed at the planted lines with a verdict other than "matches".

| Statement | Plant | What was planted | Result | Row that flagged it |
| --- | --- | --- | --- | --- |
| FiniteCongruenceGraph | one-direction | Only one direction of the paper's 'if and only if': a graph witness gives a representation, but not the converse. | caught | Direction of the conclusion (iff vs. one direction) (Lean concludes less) |
| FiniteCongruenceGraph | placement-reversed | Admissible placements must raise edge colours where the paper's lower them: d(p,q) ≤ d(f(p),f(q)) instead of d(f(p),f(q)) ≤ d(p,q). | caught | Admissible placement (direction of the inequality) (differs) |
| FourRowPermanent | exponent-two-allowed | Allows p₀ = 2, where the inequality was already known; the paper's point is an exponent strictly below two. | caught | Range of the exponent p₀ (Lean concludes less) |
| FourRowPermanent | unnormalized-norm | Row norms drop the paper's 1/4 normalization, which enlarges the right-hand side and weakens the inequality. The file's own comment still says the norms are normalized. | caught | Definition of the p-norm (normalization) (differs) |
| PlaneColoring | line-not-plane | Colours the real line, not the plane. | caught | Ambient space ("the Euclidean plane") (differs) |
| PlaneColoring | bounded-region | Only points within distance 100 of the origin need different colours at distance one. | caught | Domain of the coloring constraint (Lean covers a special case) |

## What the unchanged copies' audits flagged

Differences the helper reported in the real statements, to compare with OpenAI's scope notes (which the helper never saw).

### FiniteCongruenceGraph (scope note 206.md)
- Remark on finite checkability for fixed |A|: not in the formalization

### FourRowPermanent (scope note 238.md)
- nothing flagged

### PlaneColoring (scope note 158.md)
- Main claim: no proper five-coloring (χ(R^2) ≥ 6): Lean concludes less (affects the main result)
- Transfer theorem and weak measurable five-coloring obstruction (Thms 1.3, 1.4): not in the formalization (affects the main result)
