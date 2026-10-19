<!-- First run of `scry statement-benchmark` (2026-10-18), commits 7d9c433..df69967, model anthropic/claude-opus-5.5 at effort high. Re-scored on 2026-10-19 from the rows it saved, under the stricter rule: no audit was run again. Before then, "unclear" counted as a catch and a "matches" row at a caught plant was not shown; this run had no "unclear" rows at its plants, but three catches had a "matches" row about another item on overlapping lines, now scored "conflicting". The run's setups were not recorded (Scry did not record them yet), and six of its nine audits were reused from an earlier run; the FourRowPermanent audits could read only one paper's copy of file names its ten papers share (see docs/decisions/0009-evidence-identity.md). Statements and paper material come from OpenAI's mathematics repository (https://github.com/openai/math), used under its Apache-2.0 license. -->

# Statement audit benchmark

6 planted differences in 3 statements: 3 caught, 3 conflicting, 0 dangerous miss, 0 unresolved, 0 missed. Total cost $8.77.

Scored mechanically from the rows each audit recorded, at the planted lines: **caught**: a row named a difference there, and none said "matches"; **conflicting**: one row named a difference there and another said "matches"; **dangerous miss**: a row said "matches" there and none named a difference; **unresolved**: the only rows there said "unclear"; **missed**: no row pointed there. A score says where an audit pointed, not whether its row describes the planted change: that is for a person to judge, row by row. The audits are the AI helper's reading.

| Statement | Plant | What was planted | Result | Rows at the planted lines | Audit |
| --- | --- | --- | --- | --- | --- |
| FiniteCongruenceGraph | one-direction | Only one direction of the paper's 'if and only if': a graph witness gives a representation, but not the converse. | conflicting | Direction of the conclusion (iff vs. one direction) (Lean concludes less); Lattice hypotheses (matches) | ran 2026-10-18 (time not recorded) |
| FiniteCongruenceGraph | placement-reversed | Admissible placements must raise edge colours where the paper's lower them: d(p,q) ≤ d(f(p),f(q)) instead of d(f(p),f(q)) ≤ d(p,q). | caught | Admissible placement (direction of the inequality) (differs) | ran 2026-10-18 (time not recorded) |
| FourRowPermanent | exponent-two-allowed | Allows p₀ = 2, where the inequality was already known; the paper's point is an exponent strictly below two. | conflicting | Range of the exponent p₀ (Lean concludes less); Conclusion inequality (matches) | ran 2026-10-18 (time not recorded) |
| FourRowPermanent | unnormalized-norm | Row norms drop the paper's 1/4 normalization, which enlarges the right-hand side and weakens the inequality. The file's own comment still says the norms are normalized. | caught | Definition of the p-norm (normalization) (differs) | ran 2026-10-18 (time not recorded) |
| PlaneColoring | line-not-plane | Colours the real line, not the plane. | caught | Ambient space ("the Euclidean plane") (differs) | ran 2026-10-18 (time not recorded) |
| PlaneColoring | bounded-region | Only points within distance 100 of the origin need different colours at distance one. | conflicting | Domain of the coloring constraint (Lean covers a special case); Color set and number of colors (matches); Plane and metric (matches) | ran 2026-10-18 (time not recorded) |

## What the unchanged copies' audits flagged

Differences the helper reported in the real statements, to compare with OpenAI's scope notes (which the helper never saw).

### FiniteCongruenceGraph (scope note 206.md)
- Remark on finite checkability for fixed |A|: not in the formalization

### FourRowPermanent (scope note 238.md)
- nothing flagged

### PlaneColoring (scope note 158.md)
- Main claim: no proper five-coloring (χ(R^2) ≥ 6): Lean concludes less (affects the main result)
- Transfer theorem and weak measurable five-coloring obstruction (Thms 1.3, 1.4): not in the formalization (affects the main result)
