## Audit report: `OAI.FourRow.robust_permanent` against Theorem 1.1 of "A strict four-row permanent inequality and permutation moments"

### 1. The paper's claim
Theorem 1.1, "A robust four-row inequality", in `A-strict-four-row-permanent-inequality-and-permutation-moments-September-26-2026/sections/01-introduction.tex`, lines 14–25 [E4]:

> There are absolute constants $p_0\in(4/3,2)$ and $\varepsilon>0$ with the following property. Let $\nu$ be a probability measure on $S_4$ such that $\|\nu-u\|_{\TV}<\varepsilon$, $\nu\{\pi:\pi(i)=j\}=\frac14$ $(1\le i,j\le4)$. Then every four nonnegative functions on $\{1,2,3,4\}$ satisfy $\E_\nu\prod_{i=1}^4f_i(\pi(i))\le\prod_{i=1}^4\|f_i\|_{p_0}$.

The paper defines the norm as $\|f\|_p=(\frac14\sum_j f(j)^p)^{1/p}$, and total variation as half the sum of absolute differences of the masses (lines 6–8 and 28) [E4]. It also says why $p_0<2$ matters: the recursion uses $\theta=1-1/p_0<1/2$, and "this strict improvement over one half is the feature the dimension comparison needs" (line 64) [E4].

### 2. The formal statement
There is a real $p_0$ with $4/3<p_0\le 2$ and an $\varepsilon>0$ such that the following holds for every real-valued mass function $\nu$ on $\mathrm{Perm}(\mathrm{Fin}\,4)$. Suppose $\nu$ is nonnegative with total mass 1, satisfies $\tfrac12\sum_\pi|\nu\pi-1/24|<\varepsilon$, and has every coordinate marginal equal to 1/4. Then every nonnegative $f:\mathrm{Fin}\,4\to\mathrm{Fin}\,4\to\mathbb R$ satisfies $\sum_\pi \nu\pi\prod_i f_i(\pi i)\le\prod_i\big((\sum_j f_i(j)^{p_0})/4\big)^{1/p_0}$ [E1, E2].

### 3. Point by point
| Item | Paper says | Lean says | Verdict |
|---|---|---|---|
| Range of $p_0$ | $p_0\in(4/3,2)$, open; $p_0<2$ gives $\theta<1/2$ [E4] | $4/3<p_0\le 2$, so $p_0=2$ is allowed [E2, E5] | **Lean concludes less** |
| Quantifier order | Absolute constants $p_0,\varepsilon$ come first, then every $\nu$ and every $f$ [E4] | Same order [E1] | matches |
| Probability measure | $\nu$ is a probability measure on $S_4$ [E4] | Masses are nonnegative and sum to 1 [E2]; the uniform law satisfies this with TV = 0 [E6] | matches |
| TV hypothesis | Half the $\ell^1$ distance to uniform is $<\varepsilon$ [E4] | $(\sum_\pi\lvert\nu\pi-1/24\rvert)/2<\varepsilon$ [E2] | matches |
| Marginals | $\nu\{\pi(i)=j\}=1/4$ for all $i,j$ [E4] | Same, written as a sum over permutations [E2] | matches |
| Normalized norm | $(\frac14\sum f^p)^{1/p}$ [E4] | $((\sum f^p)/4)^{1/p}$ with real powers; $f\ge0$ [E2] | matches |
| Conclusion | $\E_\nu\prod f_i(\pi(i))\le\prod\|f_i\|_{p_0}$ [E4] | $\sum_\pi\nu\pi\prod f_i(\pi i)\le\prod\mathrm{lpNorm}\,p_0\,(f_i)$ [E2] | matches |

### 4. Definitions a person should read closely
- **The exponent bound on line 38: `p₀ ≤ 2` where the paper has $p_0<2$.** This is the one real discrepancy.
  - The normalized norms $\|f\|_p$ do not decrease as $p$ grows. So if the inequality holds for some $p_0\le 2$, it also holds at $p=2$. Conversely, $p_0=2$ is itself an allowed witness [E5].
  - The Lean statement is therefore equivalent to the robust inequality at exponent 2 alone, and the condition $4/3<p_0$ adds nothing.
  - The exponent-2 version is still a real perturbation statement around Carlen–Lieb–Loss, but it loses the strict gap $\theta<1/2$ that the paper says its recursion needs [E4].
- `lpNorm` (lines 31–32) uses real powers. Since the functions are nonnegative and $p_0>0$, it agrees with the paper's norm [E2].
- `totalVariation` and `UniformMarginals` (lines 25–29) match the paper's definitions exactly [E2, E4].

### 5. Lean checks I ran
- **[E5]:** I gave Lean, as a hypothesis, the robust statement with exponent fixed at 2, and it derived `robust_permanent` by taking $p_0=2$. This confirms that a $p_0=2$ witness is enough to satisfy the formal statement. (The reverse direction rests on power-mean monotonicity, which I argued by hand and did not check in Lean.)
- **[E6]:** The uniform law $1/24$ satisfies `IsProbability` and has `totalVariation` 0. So the hypotheses can be met, and the statement is not vacuous on that front.

### 6. Overall
The objects, hypotheses, quantifier order, norm normalization and conclusion all match the paper's Theorem 1.1. The one exception is the exponent range: Lean allows $p_0=2$, which makes the formal statement equivalent to the robust inequality at exponent 2 [E5]. The formal statement is implied by the paper's theorem but does not capture its key content, the strict improvement $p_0<2$. To match the paper, line 38 should read `p₀ < 2`.

## Rows the helper recorded

| Item | Verdict | Affects main result | Lean lines | Evidence |
| --- | --- | --- | --- | --- |
| Range of the exponent p0 | Lean concludes less | yes | 38-38 | E1, E2, E4, E5 |
| Quantifier order (absolute constants p0, ε before ν, f) | matches | no | 38-41 | E1, E4 |
| Probability measure on S4 | matches | no | 17-23 | E2, E6 |
| Total-variation hypothesis | matches | no | 28-29 | E2, E4 |
| Uniform marginal hypothesis | matches | no | 25-26 | E2, E4 |
| Normalized p-norm | matches | no | 31-32 | E2, E4 |
| Conclusion: permanent-type inequality | matches | no | 34-42 | E2, E4 |

## Evidence

- E1: Lean's reading of the statement of robust_permanent [Lean (checks the math itself)]
- E2: Lean statement lines 1-48 [lookup (no check)]
- E3: paper search for 'robust' [lookup (no check)]
- E4: paper A-strict-four-row-permanent-inequality-and-permutation-moments-September-26-2026/sections/01-introduction.tex lines 1-68 [lookup (no check)]
- E5: Lean check of claim 1: accepted [Lean (checks the math itself)]
- E6: Lean check of claim 2: accepted [Lean (checks the math itself)]
- E7: verdict 1: Range of the exponent p0 (Lean concludes less) [lookup (no check)]
- E8: verdict 2: Quantifier order (absolute constants p0, ε before ν, f) (matches) [lookup (no check)]
- E9: verdict 3: Probability measure on S4 (matches) [lookup (no check)]
- E10: verdict 4: Total-variation hypothesis (matches) [lookup (no check)]
- E11: verdict 5: Uniform marginal hypothesis (matches) [lookup (no check)]
- E12: verdict 6: Normalized p-norm (matches) [lookup (no check)]
- E13: verdict 7: Conclusion: permanent-type inequality (matches) [lookup (no check)]

(Cost of this audit: $0.3881.)
