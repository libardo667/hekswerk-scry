## Audit report: `OAI.FourRow.robust_permanent` against the paper's Theorem 1.1

### 1. The paper's claim
This is Theorem `thm:permanent`, "A robust four-row inequality", in *A strict four-row permanent inequality and permutation moments*, `sections/01-introduction.tex`, lines 14–25 [E5]:

> There are absolute constants $p_0\in(4/3,2)$ and $\varepsilon>0$ with the following property. Let $\nu$ be a probability measure on $S_4$ such that $\|\nu-u\|_{\TV}<\varepsilon$, $\nu\{\pi:\pi(i)=j\}=\frac14\ (1\le i,j\le4)$. Then every four nonnegative functions on $\{1,2,3,4\}$ satisfy $\E_\nu\prod_{i=1}^4f_i(\pi(i))\le\prod_{i=1}^4\|f_i\|_{p_0}$.

The paper defines the norm as $\|f\|_p=(\frac14\sum_j f(j)^p)^{1/p}$ (lines 6–9). It defines total variation as "one half the sum of the absolute differences of the probability masses" (line 28). Here $u$ is the uniform measure on $S_4$ [E5].

### 2. The formal statement
There is a real $p_0$ with $4/3<p_0<2$, and an $\varepsilon>0$, with the following property [E1, E3]. Take any real-valued mass function $\nu$ on the permutations of `Fin 4` that:
- is nonnegative with total mass 1,
- satisfies $\tfrac12\sum_\pi|\nu(\pi)-1/24| < \varepsilon$, and
- gives every event $\{\pi(i)=j\}$ mass exactly $1/4$.

Then for every nonnegative $4\times4$ real array $f$:
$$\sum_\pi \nu(\pi)\prod_i f_i(\pi(i)) \;\le\; \prod_i \Big(\tfrac14\sum_j f_i(j)^{p_0}\Big)^{1/p_0}.$$

The theorem has no extra hypotheses of its own [E1].

### 3. Point by point
| Item | Paper says | Lean says | Verdict |
|---|---|---|---|
| Constants and quantifier order | Absolute constants $p_0\in(4/3,2)$ and $\varepsilon>0$, chosen before $\nu$ and $f$ [E5] | `∃ p₀, 4/3 < p₀ ∧ p₀ < 2 ∧ ∃ ε, 0 < ε ∧ ∀ ν … ∀ f …` (lines 37–42) [E1, E3] | matches [E7] |
| Probability measure on $S_4$ | $\nu$ is a probability measure on $S_4$ [E5] | `Perm (Fin 4) → ℝ`, every mass ≥ 0, total mass 1 (lines 17–23) [E3]; the hypotheses can be satisfied [E6] | matches [E8] |
| TV hypothesis | $\|\nu-u\|_{TV}<\varepsilon$, with TV = half the sum of absolute differences [E5] | `(∑ |ν π − 1/24|)/2 < ε` (lines 28–29) [E3] | matches [E9] |
| Uniform marginals | $\nu\{\pi(i)=j\}=1/4$ for all $i,j$ [E5] | `∀ i j, ∑ π, (if π i = j then ν π else 0) = 1/4` (lines 25–26) [E3] | matches [E10] |
| Normalized $\ell^p$ norm | $((1/4)\sum_j f(j)^p)^{1/p}$ [E5] | `((∑ j, f j ^ p)/4)^(1/p)` with real powers (lines 31–32) [E3] | matches [E11] |
| Conclusion | $\E_\nu\prod_i f_i(\pi(i))\le\prod_i\|f_i\|_{p_0}$ for nonnegative $f_i$ [E5] | `∑ π, ν π * ∏ i, f i (π i) ≤ ∏ i, lpNorm p₀ (f i)` for all `f` with `0 ≤ f i j` (lines 34–42) [E3] | matches [E12] |

### 4. Definitions a person should read closely
- **`lpNorm`** (lines 31–32) [E3]. It uses Lean's real power `rpow`, which is badly behaved for negative bases. That does not matter here, because the theorem only applies `lpNorm` to rows with nonnegative entries. Zero entries give $0^{p_0}=0$ since $p_0>0$. The division by 4 matches the paper's normalization.
- **`totalVariation`** (lines 28–29) [E3]. It hard-codes the uniform mass as $1/24 = 1/|S_4|$ and includes the factor ½, as the paper's convention requires [E5].
- **`UniformMarginals`** (lines 25–26) [E3]. It writes the event mass as a sum of `if` terms over permutations. This is a faithful encoding of $\nu\{\pi:\pi(i)=j\}$.

### 5. Lean checks I ran
- **[E6]** The uniform law $\nu\equiv1/24$ satisfies `IsProbability` and `UniformMarginals`, and has `totalVariation` equal to 0. Lean accepted this. So the hypotheses can be met, and the uniform law is covered for every $\varepsilon>0$. This also confirms that the marginal and total-variation definitions compute what the paper means on the basic example.

### 6. Overall
The Lean statement matches the paper's Theorem 1.1 on every item:
- the same constants and the same order of quantifiers ($p_0$ and $\varepsilon$ chosen before $\nu$ and $f$);
- the same strict total-variation bound and exact uniform marginals;
- the same normalized norm and the same inequality for nonnegative functions.

I found no gaps in either direction. A proof of this formal statement would establish exactly the paper's robust four-row inequality.

## Rows the helper recorded

| Item | Verdict | Affects main result | Lean lines | Evidence |
| --- | --- | --- | --- | --- |
| Constants and quantifier order (p0 ∈ (4/3,2), ε>0, then for all ν, f) | matches | yes | 37-42 | E1, E3, E5 |
| Probability measure on S_4 | matches | yes | 17-23 | E3, E5, E6 |
| Total variation hypothesis | matches | yes | 28-29 | E3, E5 |
| Uniform coordinate marginals | matches | yes | 25-26 | E3, E5, E6 |
| Normalized ℓ^p norm | matches | yes | 31-32 | E3, E5 |
| Conclusion: permanent-type expectation bound | matches | yes | 34-42 | E1, E3, E5 |

## Evidence

- E1: Lean's reading of the statement of robust_permanent [Lean (checks the math itself)]
- E2: paper search for 'four-row permanent' [lookup (no check)]
- E3: Lean statement lines 1-48 [lookup (no check)]
- E4: paper search for 'robust' [lookup (no check)]
- E5: paper A-strict-four-row-permanent-inequality-and-permutation-moments-September-26-2026/sections/01-introduction.tex lines 1-68 [lookup (no check)]
- E6: Lean check of claim 1: accepted [Lean (checks the math itself)]
- E7: verdict 1: Constants and quantifier order (p0 ∈ (4/3,2), ε>0, then for all ν, f) (matches) [lookup (no check)]
- E8: verdict 2: Probability measure on S_4 (matches) [lookup (no check)]
- E9: verdict 3: Total variation hypothesis (matches) [lookup (no check)]
- E10: verdict 4: Uniform coordinate marginals (matches) [lookup (no check)]
- E11: verdict 5: Normalized ℓ^p norm (matches) [lookup (no check)]
- E12: verdict 6: Conclusion: permanent-type expectation bound (matches) [lookup (no check)]

(Cost of this audit: $0.3287.)
