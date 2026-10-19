# Statement audit benchmark

2 planted differences in 1 statements: 1 caught, 1 conflicting, 0 dangerous miss, 0 unresolved, 0 missed. Total cost $2.01.

Scored mechanically from the rows each audit recorded, at the planted lines: **caught**: a row named a difference there, and none said "matches"; **conflicting**: one row named a difference there and another said "matches"; **dangerous miss**: a row said "matches" there and none named a difference; **unresolved**: the only rows there said "unclear"; **missed**: no row pointed there. A score says where an audit pointed, not whether its row describes the planted change: that is for a person to judge, row by row. The audits are the AI helper's reading.

| Statement | Plant | What was planted | Result | Rows at the planted lines | Audit |
| --- | --- | --- | --- | --- | --- |
| FourRowPermanent | exponent-two-allowed | Allows p₀ = 2, where the inequality was already known; the paper's point is an exponent strictly below two. | conflicting | Range of the exponent p0 (Lean concludes less); Quantifier order (absolute constants p0, ε before ν, f) (matches); Conclusion: permanent-type inequality (matches) | ran 2026-10-19 15:10:25 UTC |
| FourRowPermanent | unnormalized-norm | Row norms drop the paper's 1/4 normalization, which enlarges the right-hand side and weakens the inequality. The file's own comment still says the norms are normalized. | caught | L^p norm normalization (differs) | ran 2026-10-19 15:11:46 UTC |

## What the unchanged copies' audits flagged

Differences the helper reported in the real statements, to compare with OpenAI's scope notes (which the helper never saw).

### FourRowPermanent (scope note 238.md)
- nothing flagged
