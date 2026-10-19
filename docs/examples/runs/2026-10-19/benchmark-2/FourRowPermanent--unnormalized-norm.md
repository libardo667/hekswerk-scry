## Audit report: `OAI.FourRow.robust_permanent`

**Result:** the formal statement does not capture the paper's theorem. Its ℓ^p norm leaves out the paper's 1/4 factor, and that makes the inequality trivially true. Lean accepted a short proof of it that uses neither of the two hypotheses.

### 1. The paper's claim
From *A strict four-row permanent inequality and permutation moments*, `sections/01-introduction.tex`, lines 14–25 [E4]:

> **Theorem (A robust four-row inequality).** There are absolute constants $p_0\in(4/3,2)$ and $\varepsilon>0$ with the following property. Let $\nu$ be a probability measure on $S_4$ such that $\|\nu-u\|_{\TV}<\varepsilon$ and $\nu\{\pi:\pi(i)=j\}=\frac14$ for $1\le i,j\le4$. Then every four nonnegative functions on $\{1,2,3,4\}$ satisfy $\E_\nu\prod_{i=1}^4f_i(\pi(i))\le\prod_{i=1}^4\|f_i\|_{p_0}$.

The norm is defined just before it (line 8): $\|f\|_p=\left(\frac14\sum_{j=1}^4 f(j)^p\right)^{1/p}$, the norm for the uniform probability on four points. Total variation is defined after it as half the sum of the absolute differences of the masses [E4].

### 2. The formal statement
There exist p₀ with 4/3 < p₀ < 2 and ε > 0 such that the following holds. Take any ν : Perm (Fin 4) → ℝ whose masses are nonnegative and sum to 1, with (∑|ν π − 1/24|)/2 < ε and every coordinate marginal equal to 1/4. Then for every nonnegative f : Fin 4 → Fin 4 → ℝ,

∑_π ν π ∏_i f i (π i) ≤ ∏_i (∑_j f i j ^ p₀)^(1/p₀) [E1, E2].

The norm `lpNorm` (lines 31–32) is the **unnormalized** counting norm: there is no factor 1/4 [E2]. The file's header comment says "All row norms use the uniform counting normalization" [E2], but the definition's body does not divide by 4.

### 3. Point by point

| Item | Paper says | Lean says | Verdict |
|---|---|---|---|
| L^p norm normalization | ((1/4)∑ f(j)^p)^{1/p} [E4] | (∑ f j ^ p)^(1/p), which is 4^{1/p} times the paper's norm [E2] | **differs** [E16] |
| Conclusion (inequality) | E_ν ∏ f_i(π(i)) ≤ ∏‖f_i‖_{p₀}, normalized norm [E4] | Same shape, but the right side is 4^{4/p₀} times larger. It holds for every probability ν, without the TV or marginal hypotheses [E15] | **Lean concludes less** [E17] |
| Quantifiers, p₀ ∈ (4/3,2), ε > 0 | ∃ p₀, ∃ ε, ∀ ν, ∀ f [E4] | Same order and ranges [E1] | matches [E18] |
| Probability measure on S₄ | probability measure [E4] | nonnegative masses summing to 1 on Perm (Fin 4) [E2] | matches [E19] |
| TV hypothesis | half the sum of \|ν − u\| is less than ε [E4] | (∑\|ν π − 1/24\|)/2 < ε [E2] | matches [E20] |
| Uniform marginals | ν{π(i)=j} = 1/4 [E4] | sum of ν π over π with π i = j equals 1/4 [E2] | matches [E21] |
| Functions and expectation | nonnegative f_i; E_ν ∏ f_i(π(i)) [E4] | f i j ≥ 0; ∑ ν π ∏ f i (π i) [E2] | matches [E22] |

### 4. Definitions a person should read closely
- **`lpNorm`** (lines 31–32): this is the key defect. Each entry satisfies f(j) ≤ (∑_k f(k)^p)^{1/p}. So ∏_i f_i(π(i)) ≤ ∏_i lpNorm(f_i) for every π, and averaging over any probability ν gives the bound at once. The robust-stability content of the paper (the perturbation around the Carlen–Lieb–Loss exponent-2 bound and the role of the endpoint 4/3) disappears completely. With the paper's normalization, the bound is false for the uniform law below p_c = 4 log 4 / log 24 [E4]; with Lean's normalization it holds for every p > 0.
- The other definitions (`IsProbability`, `UniformMarginals`, `totalVariation`, `permanentExpectation`) faithfully match the paper [E2, E4].

### 5. Lean checks I ran
- **[E7]** Lean accepted the lemma that for p > 0 and nonnegative g, every entry satisfies g j ≤ lpNorm p g.
- **[E14]** Lean accepted the helper lemma that a product of nonnegative terms is monotone in each term (proved with `gcongr`).
- **[E15]** Lean accepted a full proof of the exact `robust_permanent` statement, with p₀ = 3/2 and ε = 1. The proof never uses the total-variation or uniform-marginal hypotheses (they are discarded as `_`). It only uses nonnegativity of ν, total mass 1, and the entry bound above. This shows the formal statement is trivially true and much weaker than the paper's theorem.
- **[E5, E6, E8–E11, E13]** These were earlier attempts that Lean rejected because of my own tactic or lemma-name mistakes (for example a `Finset.prod_le_prod` signature mismatch). They show nothing about the statement. **[E12]** was only a probe that still contained `sorry`.

### 6. Overall
The hypotheses and quantifiers match the paper, but the conclusion uses an unnormalized ℓ^p norm instead of the paper's normalized one. That inflates the right-hand side by a factor of 4^{4/p₀} and turns the statement into a triviality. Lean confirmed this by accepting a proof that ignores the TV and marginal hypotheses [E15]. A proof of this formal statement therefore says nothing about the paper's robust four-row permanent inequality. To fix it, `lpNorm` should be defined as ((1/4)∑ f(j)^p)^{1/p}.

## Rows the helper recorded

| Item | Verdict | Affects main result | Lean lines | Evidence |
| --- | --- | --- | --- | --- |
| L^p norm normalization | differs | yes | 31-32 | E2, E4, E15 |
| Conclusion (inequality) | Lean concludes less | yes | 37-42 | E2, E4, E15 |
| Quantifiers and constants p₀ ∈ (4/3,2), ε > 0 | matches | no | 38-39 | E1, E4 |
| Probability measure on S_4 | matches | no | 17-23 | E2, E4 |
| Total variation hypothesis | matches | no | 28-29 | E2, E4 |
| Uniform marginals hypothesis | matches | no | 25-26 | E2, E4 |
| Functions and expectation | matches | no | 34-41 | E2, E4 |

## Evidence

- E1: Lean's reading of the statement of robust_permanent [Lean (checks the math itself)]
- E2: Lean statement lines 1-48 [lookup (no check)]
- E3: paper search for 'robust' [lookup (no check)]
- E4: paper A-strict-four-row-permanent-inequality-and-permutation-moments-September-26-2026/sections/01-introduction.tex lines 1-68 [lookup (no check)]
- E5: Lean check of claim 1: not accepted [Lean (checks the math itself)]
- E6: Lean check of claim 2: not accepted [Lean (checks the math itself)]
- E7: Lean check of claim 3: accepted [Lean (checks the math itself)]
- E8: Lean check of claim 4: not accepted [Lean (checks the math itself)]
- E9: Lean check of claim 5: not accepted [Lean (checks the math itself)]
- E10: Lean check of claim 6: not accepted [Lean (checks the math itself)]
- E11: Lean check of claim 7: not accepted [Lean (checks the math itself)]
- E12: Lean check of claim 8: not accepted [Lean (checks the math itself)]
- E13: Lean check of claim 9: not accepted [Lean (checks the math itself)]
- E14: Lean check of claim 10: accepted [Lean (checks the math itself)]
- E15: Lean check of claim 11: accepted [Lean (checks the math itself)]
- E16: verdict 1: L^p norm normalization (differs) [lookup (no check)]
- E17: verdict 2: Conclusion (inequality) (Lean concludes less) [lookup (no check)]
- E18: verdict 3: Quantifiers and constants p₀ ∈ (4/3,2), ε > 0 (matches) [lookup (no check)]
- E19: verdict 4: Probability measure on S_4 (matches) [lookup (no check)]
- E20: verdict 5: Total variation hypothesis (matches) [lookup (no check)]
- E21: verdict 6: Uniform marginals hypothesis (matches) [lookup (no check)]
- E22: verdict 7: Functions and expectation (matches) [lookup (no check)]

(Cost of this audit: $1.2972.)
