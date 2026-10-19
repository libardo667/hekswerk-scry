<!-- The first live statement audit (2026-10-17), saved by `scry audit-statement TruffetCounterexample`.
Paper quotes and the scope note below come from OpenAI's mathematics repository
(https://github.com/openai/math), used under its Apache-2.0 license. -->

# Statement audit of TruffetCounterexample, next to OpenAI's scope note

## Scry's audit (the AI helper's reading, except where it cites a Lean check)

1. **The paper's claim** (source/sections/09-comparison.tex, lines 12–73 [E4]). The paper looks at the instance "min x₁ subject to max(x₁,x₂) ≥ 0, x₁ ≥ max(x₂+1, −2)" and argues: "The point (0,−1) is feasible… Thus the true minimum is exactly zero." After homogenizing to "max(x₁,x₂) ≥ h, x₁ ≥ max(x₂+1, h−2)", it says the dominating-variable set is exactly {x₂} and the "unique pair (1,2)" forces "x₂ = h. There is no tie-breaking choice in this step." Then "the second row requires x₁ ≥ h+1. The next eligible saturation consequently sets x₁ = h+1. The stopping test in Equation (39) fails before each of these two substitutions… the separate rule for an objective-independent switch to maximization does not apply. Normalizing to h=0 gives objective value 1, whereas the original minimum … is 0." It also claims: "The first substitution already removes every optimum." The scope is limited to Truffet's arXiv v4 rule [E4]; the introduction says the same [E5].

2. **The formal statement.** The theorem has no hypotheses. It asserts a conjunction about fixed concrete objects [E1, E6]:
   - Encoding: coordinates 0, 1, 2 stand for x₁, x₂, h. Row 0 is max(x₁,x₂) ≥ h. Row 1 is x₁ ≥ max(x₂+1, h−2). The cost is x₁. Rows and variables are indexed from 0, so the paper's pair (1,2) is Lean's `(row 0, var 1)`.
   - The instance satisfies a cross-row non-domination condition (`crossRowRestriction`).
   - `initial → middle` is a `ForcedSingletonStep` on (row 0, x₂). `middle → finalState` is one on (row 1, x₁).
   - At `finalState` no variable remains and `stop` holds.
   - `output = (1,0,0)` and `better = (0,−1,0)` are both feasible for the original rows, and both have h = 0.
   - `output` is produced by back-substituting x₂ = h and then x₁ = h+1.
   - The original cost at `output` equals the final cost at `output`, and the original cost at `better` is strictly smaller than that.

3. **Point by point**

| Item | Paper says | Lean says | Verdict |
|---|---|---|---|
| Instance and homogenization | max(x₁,x₂) ≥ h; x₁ ≥ max(x₂+1, h−2); objective x₁ [E4] | `initial` rows and cost encode exactly this, in max-plus over `WithBot ℝ` [E6, lines 93–97] | matches |
| Eq. (5b) cross-row condition | for both ordered row pairs, no domination by any finite additive constant [E4] | `crossRowRestriction`: for i≠r and every α there is a w with lhsᵢ(w) < α + rhsᵣ(w) [E6, lines 110–112] | matches the paper's prose. Whether it matches Truffet's Eq. (5b) cannot be checked here |
| Every variable has a lower or upper occurrence | required by Def. 4.2 / Eq. (34) [E4] | `bounded`, part of `ForcedSingletonStep` [E6] | matches |
| Search endpoints μ=0, λ=−4 and Eq. (23b) | claimed to hold [E4] | absent | not in the formalization |
| Lower/upper occurrence table, dominating set {x₂}, unique eligible pair | [E4] | `lower`, `upper`, `dominating`, `eligible`; the step requires eligible ⇔ (r,k)=(0,1) [E6, lines 39–51, 89]. My hand computation agrees with the paper's table | matches, within the formalizer's model of the rule |
| First substitution x₂ = h | [E4] | `lowerForm initial 0 1` = (⊥,⊥,0), i.e. x₂ = h; `advance` gives `middle`, whose row 1 is x₁ ≥ h+1 [E6] | matches |
| Stop test fails before each step; no switch; no failure | [E4] | `¬stop`, `¬switch`, `¬failure` are inside each `ForcedSingletonStep` [E6, line 88] | matches, within the model |
| Second substitution x₁ = h+1; final objective h+1 | [E4] | `finalState.cost` = (⊥,⊥,1); `stop finalState`; no variables remain [E1, E6] | matches |
| Output value 1 vs. a feasible point of value 0 | [E4] | `output` and `better` are feasible, with eval values 1 and 0 [E1]; I confirmed the values separately [E9] | matches |
| "True minimum is exactly zero" | every feasible point has x₁ ≥ 0 [E4] | the theorem only exhibits `better` with value 0 < 1 | Lean concludes less. I proved the lower bound separately [E7] |
| "First substitution already removes every optimum" | [E4] | not stated | Lean concludes less. I proved separately that x₁ ≥ 1 on `middle` when h = 0 [E10] |
| Fidelity to Truffet v4 itself | the paper cites specific equations (5b, 23b, 39, 47, 53a/b, Case 2.2.2) [E4] | the rule is the formalizer's own reconstruction: `ForcedSingletonStep`, `advance`, `cleanup`, `stop`, `switch` [E6] | unclear; cannot be checked against the source |

4. **Definitions a person should read closely**
   - `lower` and `upper`: a strict comparison of the left-side and right-side coefficients of a column. These decide the dominating set.
   - `eligible`: restricts to dominating variables whenever one exists (Eq. 53b).
   - `lowerForm`, `substitute`, `cleanup`, `advance`: the saturation and substitution mechanics. `cleanup` replaces a row by a null row when it is trivially satisfied coefficient-wise.
   - `stop` (the h-coefficient test, Eq. 39) and `switch`.
   - `crossRowRestriction` (Eq. 5b).

   All of these are the formalizer's model of Truffet's procedure. The audited theorem is only as meaningful as the match between this model and the cited v4 text, which this audit cannot see.

5. **Lean checks I ran**
   - [E7] accepted: every w feasible for `initial` with h = 0 has x₁ ≥ 0. This supports "the true minimum is exactly zero".
   - [E8] rejected: a combined attempt failed because of my tactics, not because the claim is false. I split it into the next two checks.
   - [E9] accepted: the original cost at `better` is 0 and the final cost at `output` is 1.
   - [E10] accepted: every w feasible for `middle` with h = 0 has x₁ ≥ 1. This supports "the first substitution already removes every optimum".

6. **Overall.** The formal statement is proven. It faithfully encodes the paper's concrete instance, the forced two-step run, and the output of value 1 against a feasible point of value 0. My side checks [E7, E10] add the paper's "minimum is 0" and "first substitution removes every optimum" claims, which the theorem itself does not state. Two things are outside the formal result: the search-endpoint conditions (μ=0, λ=−4, Eq. 23b), and whether `ForcedSingletonStep` and the related definitions really match the rule printed in Truffet's arXiv v4.

## Evidence

- E1: Lean's reading of the statement of finite_execution_not_optimal [Lean (checks the math itself)]
- E2: list of paper files [lookup (no check)]
- E3: paper search for 'truffet' [lookup (no check)]
- E4: paper source/sections/09-comparison.tex lines 1-82 [lookup (no check)]
- E5: paper source/sections/01-introduction.tex lines 175-200 [lookup (no check)]
- E6: Lean statement lines 1-134 [lookup (no check)]
- E7: Lean check of claim 1: accepted [Lean (checks the math itself)]
- E8: Lean check of claim 2: not accepted [Lean (checks the math itself)]
- E9: Lean check of claim 3: accepted [Lean (checks the math itself)]
- E10: Lean check of claim 4: accepted [Lean (checks the math itself)]

(Cost of this audit: $0.5050.)

## OpenAI's scope note (104.md), not seen by the helper

# Quasipolynomial algorithms for mean-payoff, stochastic and parity games

The following describes the scope of the Lean formalization related to the following accompanying paper(s):

- [Deterministic quasipolynomial-time mean-payoff games](../../preprints/Deterministic-quasipolynomial-time-mean-payoff-games-September-25-2026/paper.pdf)
- [Randomized quasipolynomial-time mean-payoff games](../../preprints/Randomized-quasipolynomial-time-mean-payoff-games-September-25-2026/paper.pdf)

## Scope

The formalization checks that a specified two-step execution of Truffet's elimination procedure terminates with a feasible but nonoptimal output. It is a finite counterexample to that proposed optimization step.

The formalized result gives one randomized algorithm for the complete zero-threshold winning set of every finite mean-payoff game with signed binary weights. It succeeds with probability at least $7/8$ and runs in quasipolynomial bit time on every random tape. Self-loops, parallel edges, and history-dependent strategies are allowed, and winning means a nonnegative liminf average payoff.

## Comparator links

| Result | Comparator statement |
| --- | --- |
| Finite counterexample to Truffet's optimization procedure | [TruffetCounterexample.lean](../ComparatorChallenges/TruffetCounterexample.lean) |
| Randomized quasipolynomial mean-payoff algorithm | [RandomizedMeanPayoff.lean](../ComparatorChallenges/RandomizedMeanPayoff.lean) |
