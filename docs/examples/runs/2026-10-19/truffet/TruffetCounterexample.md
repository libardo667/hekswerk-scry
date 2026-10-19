# Statement audit of TruffetCounterexample, next to OpenAI's scope note

## Scry's audit (the AI helper's reading, except where it cites a Lean check)

## Audit report: TruffetCounterexample

### 1. The paper's claim

From Appendix A of the randomized paper, `09-comparison.tex` lines 12–19 and 66–73 [E5]:

> "In ordinary arithmetic, consider min x₁ subject to max(x₁,x₂) ≥ 0, x₁ ≥ max(x₂+1,−2). The point (0,−1) is feasible. Conversely, a feasible point with x₁<0 would have x₂ ≤ x₁−1<0, contradicting the first constraint. Thus the true minimum is exactly zero."

> "After substitution the second row requires x₁ ≥ h+1. The next eligible saturation consequently sets x₁=h+1. The stopping test in Equation (39) fails before each of these two substitutions. … Normalizing to h=0 gives objective value 1, whereas the original minimum … is 0."

Earlier in the appendix, the paper says the first selection (row 1, x₂ ↦ h) is forced by Eqs. (53a)/(53b), with "no tie-breaking choice" [E5]. The introduction (lines 186–191) [E6] and the deterministic paper (lines 149–154) [E9] both limit the claim to the printed rule in arXiv:2603.26423v4.

### 2. The formal statement

The theorem has no hypotheses. It is one conjunction about a single concrete instance. Variables are columns (x₁, x₂, h), and forms are max-plus over `WithBot ℝ` [E1, E4]. The conjuncts say:

- `initial` satisfies the cross-row condition: for every pair of distinct rows i ≠ r and every real α, some point w has lhsᵢ(w) < α + rhsᵣ(w).
- The step from `initial` to `middle` is a forced singleton step on (row 0, variable x₂). Here "forced" means:
  - both states are well formed;
  - the state is bounded;
  - neither the stop, switch nor failure condition holds;
  - (row 0, x₂) is the only eligible pair;
  - the objective stays non-trivial after substitution;
  - `middle` is exactly `advance initial 0 1`.
- The step from `middle` to `finalState` is a forced singleton step on (row 1, x₁).
- `finalState` has no remaining variables, and its stop condition holds.
- `output` = (1, 0, 0) and `better` = (0, −1, 0) are both feasible for `initial`, and both have h = 0.
- `output` agrees with both saturations: x₂ = h and x₁ = h+1.
- The original objective at `output` equals the final objective at `output`.
- The original objective at `better` is strictly below the final objective at `output`.

### 3. Point by point

| Item | Paper says | Lean says | Verdict |
|---|---|---|---|
| Instance (rows, objective) | min x₁; max(x₁,x₂) ≥ h; x₁ ≥ max(x₂+1, h−2) [E5] | `initial`: row 0 lhs [0,0,⊥], rhs [⊥,⊥,0]; row 1 lhs [0,⊥,⊥], rhs [⊥,1,−2]; cost [0,⊥,⊥] [E4] | matches [E10] |
| Eq. (5b) cross-row condition | Holds for both ordered pairs of rows: no domination by any finite constant [E5] | `crossRowRestriction`: ∀ i≠r, ∀ α, ∃ w, lhsᵢ(w) < α + rhsᵣ(w) [E4] | matches [E11] |
| Search endpoints μ=0, λ=−4 and Eq. (23b) | Endpoints chosen and checked [E5] | Absent [E4] | not in the formalization [E12] |
| Lower/upper occurrences, dominating set, boundedness | Occurrences come from constraint rows only; dominating set is {x₂} [E5] | `lower`, `upper`, `dominating` and `bounded` use only `s.rows`, never the cost [E4] | matches [E13] |
| Forced first selection | Unique eligible pair (row 1, x₂), giving x₂ = h [E5] | Eligibility holds exactly for (0, 1); `middle = advance initial 0 1` [E1, E4] | matches [E20] |
| Second step and termination | x₁ = h+1; the stop test fails before each step; the switch rule does not apply [E5] | Second forced step; final state has no remaining variables, stop holds, cost is h+1 [E1, E4] | matches [E15] |
| Fidelity of the modelled rule to Truffet v4 | The rule is cited only by equation numbers; Truffet's text is not among the sources [E2, E5] | stop, switch, failure and cleanup are this file's own definitions [E4] | unclear [E21] |
| Output value 1 at h=0 | Value 1 [E5] | `output` = (1,0,0), feasible, consistent with both saturations, cost 1 [E1] | matches [E17] |
| True minimum is exactly 0 | Minimum = 0 [E5] | Only states a feasible point of cost 0 < 1; the lower bound is not stated, though I derived it separately [E7, E8] | Lean concludes less [E18] |
| "First substitution removes every optimum" | Claimed [E5] | Absent [E4] | not in the formalization [E19] |

### 4. Definitions a person should read closely

- **`ForcedSingletonStep`, `eligible`, `dominating`, `lower`, `upper` (lines 39–51, 86–91).** These encode Eqs. (53a)/(53b) and the saturation step. "Forced" here means only that the modelled eligible set is a single pair.
- **`stop` (line 56).** Every row's h-coefficient on the right is at most its h-coefficient on the left. The paper refers to this test only as "Equation (39)" and never states it.
- **`switch` and `failure` (lines 58–67).** These model the alternative branches of the procedure. Their faithfulness to Truffet's text cannot be checked here.
- **`cleanup` (lines 76–78).** A row whose right side is coefficientwise at most its left side becomes the null row. This simplification is what makes `middle` and `finalState` come out as written.
- **`lowerForm` (lines 69–71).** This is the saturation x_j := rhs − lhs_j. It reads the lhs coefficient through `unbotD 0`; that is harmless here because `eligible` requires the coefficient to be finite.

I checked by hand that the instance, the two substitutions, the dominating and eligible sets, and the values at `output` and `better` all agree with the paper's description [E4, E5].

### 5. Lean checks I ran

- **[E7]** From the theorem I derived a feasible point with h = 0 whose original cost is strictly below the cost at the procedure's output, and that this output cost equals the final objective. This is the plain "output not optimal" corollary. Lean accepted it.
- **[E8]** Every feasible w with h = 0 has x₁ ≥ 0. This is the paper's "true minimum is exactly zero" lower bound, which the main theorem does not state. Lean accepted it. Together with `better`, it shows the minimum on h = 0 is exactly 0 in this model.

### 6. Overall

The formal statement encodes the paper's two-variable instance faithfully and records a two-step execution in which each step is forced. It ends at a point of value 1, while a feasible point of value 0 exists. That is the paper's conclusion; the "minimum is exactly 0" part is not in the theorem itself, though I checked it separately [E8]. What it cannot establish is that its own model of the rule (stop, switch, failure, cleanup and the eligibility rule) matches the procedure printed in Truffet's arXiv v4, because that text is not in the provided sources. The result is therefore a counterexample to the modelled rule. A reader who wants the claim about Truffet's actual procedure must compare those definitions against his paper.

Proof status (checked by Lean here): Lean, run here, accepts `OAI.TruffetV4Counterexample.finite_execution_not_optimal` in the solution module `OAI.Optimization.Tropical.TruffetCounterexample` with no sorry and only the standard axioms. Scry has not checked that the solution's statement is exactly this file's (the repository's comparator tool checks that), so rely only on this file's own statement. A proof settles the formal statement and nothing more.

## Rows the helper recorded

| Item | Verdict | Affects main result | Lean lines | Evidence |
| --- | --- | --- | --- | --- |
| Instance: constraint rows and objective | matches | yes | 93-97 | E4, E5 |
| Input condition Eq. (5b): no cross-row functional domination | matches | no | 110-119 | E4, E5 |
| Search endpoints μ=0, λ=−4 and Eq. (23b) | not in the formalization | no | - | E4, E5 |
| Lower/upper occurrences, dominating set, boundedness | matches | yes | 39-54 | E4, E5 |
| Second substitution x1 = h+1 and termination | matches | yes | 99-122 | E1, E4, E5 |
| Procedure output and its value 1 (normalized h=0) | matches | yes | 114-127 | E1, E4, E5 |
| True minimum is exactly 0; output not optimal | Lean concludes less | no | 123-128 | E1, E5, E7, E8 |
| First substitution already removes every optimum | not in the formalization | no | - | E4, E5 |
| Forced first selection (Eq 53b), no tie-breaking | matches | yes | 86-103 | E1, E4, E5 |
| Fidelity of the modeled rule (stop, switch, failure, cleanup) to Truffet v4's text | unclear | yes | 56-78 | E4, E5, E2 |

## Evidence

- E1: Lean's reading of the statement of finite_execution_not_optimal [Lean (checks the math itself)]
- E2: list of paper files [lookup (no check)]
- E3: paper search for 'truffet' [lookup (no check)]
- E4: Lean statement lines 1-134 [lookup (no check)]
- E5: paper Randomized-quasipolynomial-time-mean-payoff-games-September-25-2026/source/sections/09-comparison.tex lines 1-82 [lookup (no check)]
- E6: paper Randomized-quasipolynomial-time-mean-payoff-games-September-25-2026/source/sections/01-introduction.tex lines 178-200 [lookup (no check)]
- E7: Lean check of claim 1: accepted [Lean (checks the math itself)]
- E8: Lean check of claim 2: accepted [Lean (checks the math itself)]
- E9: paper Deterministic-quasipolynomial-time-mean-payoff-games-September-25-2026/source/sections/09-tropical.tex lines 138-154 [lookup (no check)]
- E10: verdict 1: Instance: constraint rows and objective (matches) [lookup (no check)]
- E11: verdict 2: Input condition Eq. (5b): no cross-row functional domination (matches) [lookup (no check)]
- E12: verdict 3: Search endpoints μ=0, λ=−4 and Eq. (23b) (not in the formalization) [lookup (no check)]
- E13: verdict 4: Lower/upper occurrences, dominating set, boundedness (matches) [lookup (no check)]
- E14: record_verdict failed [lookup (no check)]
- E15: verdict 5: Second substitution x1 = h+1 and termination (matches) [lookup (no check)]
- E16: record_verdict failed [lookup (no check)]
- E17: verdict 6: Procedure output and its value 1 (normalized h=0) (matches) [lookup (no check)]
- E18: verdict 7: True minimum is exactly 0; output not optimal (Lean concludes less) [lookup (no check)]
- E19: verdict 8: First substitution already removes every optimum (not in the formalization) [lookup (no check)]
- E20: verdict 9: Forced first selection (Eq 53b), no tie-breaking (matches) [lookup (no check)]
- E21: verdict 10: Fidelity of the modeled rule (stop, switch, failure, cleanup) to Truffet v4's text (unclear) [lookup (no check)]

(Cost of this audit: $0.6938.)

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
