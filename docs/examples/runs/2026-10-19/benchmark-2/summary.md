# Statement audit benchmark

6 planted differences in 3 statements: 3 caught, 3 conflicting, 0 dangerous miss, 0 unresolved, 0 missed. Total cost $5.75.

Scored mechanically from the rows each audit recorded, at the planted lines: **caught**: a row named a difference there, and none said "matches"; **conflicting**: one row named a difference there and another said "matches"; **dangerous miss**: a row said "matches" there and none named a difference; **unresolved**: the only rows there said "unclear"; **missed**: no row pointed there. A score says where an audit pointed, not whether its row describes the planted change: that is for a person to judge, row by row. The audits are the AI helper's reading.

3 of 9 audits were not run again: an earlier run did the same experiment (identical setup), and they are reused from it. Reused audits are not new tries.

| Statement | Plant | What was planted | Result | Rows at the planted lines | Audit |
| --- | --- | --- | --- | --- | --- |
| FiniteCongruenceGraph | one-direction | Only one direction of the paper's 'if and only if': a graph witness gives a representation, but not the converse. | conflicting | Direction of the theorem (iff vs one direction) (Lean concludes less); Lattice L: finite nonempty lattice with least element (matches) | ran 2026-10-28 17:05:50 UTC |
| FiniteCongruenceGraph | placement-reversed | Admissible placements must raise edge colours where the paper's lower them: d(p,q) ≤ d(f(p),f(q)) instead of d(f(p),f(q)) ≤ d(p,q). | caught | Admissible placement (direction of inequality) (differs) | ran 2026-10-28 17:07:03 UTC |
| FourRowPermanent | exponent-two-allowed | Allows p₀ = 2, where the inequality was already known; the paper's point is an exponent strictly below two. | conflicting | Range of the exponent p0 (Lean concludes less); Quantifier order (absolute constants p0, ε before ν, f) (matches); Conclusion: permanent-type inequality (matches) | reused, ran 2026-10-19 15:10:25 UTC |
| FourRowPermanent | unnormalized-norm | Row norms drop the paper's 1/4 normalization, which enlarges the right-hand side and weakens the inequality. The file's own comment still says the norms are normalized. | caught | L^p norm normalization (differs) | reused, ran 2026-10-19 15:11:46 UTC |
| PlaneColoring | line-not-plane | Colours the real line, not the plane. | caught | Ambient space ("Plane") (differs) | ran 2026-10-28 17:12:18 UTC |
| PlaneColoring | bounded-region | Only points within distance 100 of the origin need different colours at distance one. | conflicting | Domain of coloring constraint (upper bound χ ≤ 7) (Lean concludes less); Number of colors / arbitrary color classes (matches) | ran 2026-10-28 17:13:28 UTC |

## What the unchanged copies' audits flagged

Differences the helper reported in the real statements, to compare with OpenAI's scope notes (which the helper never saw).

### FiniteCongruenceGraph (scope note 206.md)
- Remark that conditions are finite checks for fixed |A|: not in the formalization

### FourRowPermanent (scope note 238.md)
- nothing flagged

### PlaneColoring (scope note 158.md)
- Main claim: no proper five-coloring (χ ≥ 6): not in the formalization (affects the main result)
