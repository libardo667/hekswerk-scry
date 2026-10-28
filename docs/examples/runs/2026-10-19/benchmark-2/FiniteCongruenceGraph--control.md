## Audit report: `OAI.FiniteCongruence.graph_criterion` against the paper's Graph criterion

### 1. The paper's claim
This is Theorem "Graph criterion" (`f:criterion`), in `sections/graph.tex`, lines 33–50 [E3]:

> The lattice $L$ is the full congruence lattice of a finite algebra if and only if there is an $L$-colored complete graph $(A,d)$ satisfying all three conditions below.
> (i) If $p\ne q$, then $d(p,q)\ne0$, and $d(p,q)\le d(p,u)\vee d(u,q)$ $(p,q,u\in A)$.
> (ii) Whenever $a\not\le b$ in $L$, there are vertices $p,q$ with $d(p,q)\le a$ and $d(p,q)\not\le b$.
> (iii) For every nonempty edge set $S$, vertices $p,q$ satisfying $d(p,q)\le a_S$ lie in the same connected component of $\Gamma_S$.

The surrounding context:
- $L$ is a finite nonempty lattice with least element $0$ [E3].
- A colored complete graph has a finite nonempty vertex set and a symmetric coloring $d$ with $d(p,p)=0$, and loops count as edges.
- A map $f$ is an admissible placement when $d'(f p, f q)\le d(p,q)$.
- $\Gamma_S$ has the adjacencies $\{f(p),f(q)\}$, where $\{p,q\}\in S$ and $f$ is admissible.
- $a_S=\bigvee_{\{p,q\}\in S} d(p,q)$ [E3].
- A finite algebra is "a nonempty finite set $A$, together with a finite list of total operations of finite nonnegative arity. The list may be empty." Representations must be onto the entire congruence lattice [E7].

### 2. The formal statement
For every finite type `Lat` with a lattice structure and a bottom element, the following two conditions are equivalent [E1, E4]:

- **`Representable Lat`:** for some `size > 0` there is an algebra on `Fin size` whose lattice of congruences is order-isomorphic to `Lat`. The algebra has finitely many operations, each of finite arity.
- **`HasGraphWitness Lat`:** for some `size > 0` there is a coloring `color : Fin size → Fin size → Lat` with these properties:
  - it is symmetric;
  - `color l r = ⊥` exactly when `l = r`;
  - it satisfies the triangle inequality;
  - it has the reflection property;
  - for every nonempty finset of ordered pairs `seeds`, any pair whose color is at most `seeds.sup color` is related by `EqvGen` of the "marked" relation. A pair `(l, r)` is marked when some admissible self-map sends some seed to `(l, r)`.

### 3. Point by point

| Item | Paper says | Lean says | Verdict |
|---|---|---|---|
| Domain of $L$ | finite nonempty lattice with $0$ [E3] | `Fintype`, `Lattice`, `OrderBot` (the bottom element makes it nonempty) [E1, E4] | matches [E10] |
| Finite algebra | nonempty finite set with a finite list of operations of finite arity, possibly empty [E7] | `numOps : ℕ`, `arity : Fin numOps → ℕ`, carrier `Fin size` with `size > 0` [E4] | matches [E11] |
| Congruences and their order | compatible equivalence relations, ordered by inclusion | compatible `Setoid`s, with the subtype order; Lean confirmed this order is inclusion [E9] | matches [E12] |
| Representability | $L\cong\mathrm{Con}(A)$, onto the full lattice [E3, E7] | `Nonempty (Lat ≃o Congruence alg)` [E4] | matches [E13] |
| Colored graph and condition (i) | symmetric $d$, $d(p,p)=0$, $d\ne0$ off the diagonal, triangle inequality [E3] | symmetry, `= ⊥ ↔ equal`, triangle inequality, vertex set `Fin size` with `size > 0` [E4] | matches [E14] |
| Condition (ii) | $a\not\le b$ ⇒ some $d(p,q)\le a$ with $d(p,q)\not\le b$ [E3] | the same statement [E4] | matches [E15] |
| Placements, $\Gamma_S$, condition (iii) | admissible maps, adjacencies are images of edges of $S$, connected components, $a_S$ is a join [E3] | `Admissible`, `Marked` (images of ordered seed pairs), `Connected` = `EqvGen`, `seeds.sup` [E4] | matches [E16] |
| Conclusion | biconditional [E3] | `Representable Lat ↔ HasGraphWitness Lat` [E1] | matches [E17] |
| Remark that the conditions are finite checks for fixed $\lvert A\rvert$ | informal remark [E3] | not stated | not in the formalization [E18] |

Notes on the encoding:
- **Ordered seed pairs.** The paper's $S$ is a set of unordered pairs; Lean uses a finset of ordered pairs. This changes nothing:
  - `EqvGen` makes the marked relation symmetric.
  - The coloring is symmetric, so the join of colors over the seeds is unchanged.
  - Every unordered set of pairs is represented by some ordered finset.
- **Loops.** Loops may be seeds in Lean, just as the paper counts loops as edges.

### 4. Definitions a person should read closely
- **`Marked` and `Connected`** (lines 32–39). These encode $\Gamma_S$ through ordered pairs and `EqvGen`. I judge this equivalent to "same connected component" in the paper's sense. Collapsed pairs (images of the form $(x,x)$) are harmless, as the paper itself says.
- **The `PartialOrder` instance on `Congruence`** (lines 22–23). It is inherited from `Setoid`, and Lean confirmed it is inclusion of relations [E9].
- **`Algebra`** (lines 10–13). It permits zero operations and nullary operations, as the paper's definition does.

### 5. Lean checks I ran
- **[E8]** `HasGraphWitness PUnit` holds, with a one-vertex witness. This matches the paper's remark that the one-element lattice is represented by the one-vertex graph. It also shows the witness conditions can be met, so the right-hand side of the equivalence is not empty by construction.
- **[E9]** For congruences `c1`, `c2`, the statement `c1 ≤ c2 ↔ ∀ x y, c1.1 x y → c2.1 x y` holds by `Iff.rfl`. So the order on the congruence lattice is inclusion, as the paper intends.

### 6. Overall
I find that the formal statement matches the paper's Graph criterion on every substantive item: the domain of $L$, the notion of finite algebra, representation onto the full congruence lattice, the three graph conditions, and the biconditional. The only difference is in encoding: seed sets use ordered pairs, with connectivity taken as the equivalence closure. I judge this equivalent to the paper's version. The informal remark that the conditions are finite checks is not formalized, and it does not affect the main claim.

## Rows the helper recorded

| Item | Verdict | Affects main result | Lean lines | Evidence |
| --- | --- | --- | --- | --- |
| Domain: finite nonempty lattice L with least element 0 | matches | no | 57-58 | E1, E3, E4 |
| Finite algebra | matches | no | 10-13 | E4, E7 |
| Congruences and their order | matches | no | 15-23 | E4, E9 |
| Representability (L ≅ full Con(A)) | matches | no | 25-26 | E3, E4, E7 |
| L-colored complete graph and condition (i) | matches | no | 41-45 | E3, E4 |
| Condition (ii) reflection | matches | no | 46-47 | E3, E4 |
| Admissible placements, Γ_S, condition (iii) connectivity | matches | no | 28-50 | E3, E4 |
| Conclusion: biconditional | matches | yes | 52-58 | E1, E3, E4, E8 |
| Remark that conditions are finite checks for fixed |A| | not in the formalization | no | - | E3, E4 |

## Evidence

- E1: Lean's reading of the statement of graph_criterion [Lean (checks the math itself)]
- E2: list of paper files [lookup (no check)]
- E3: paper sections/graph.tex lines 1-125 [lookup (no check)]
- E4: Lean statement lines 1-63 [lookup (no check)]
- E5: paper search for 'finite algebra' [lookup (no check)]
- E6: paper search for 'allowed' [lookup (no check)]
- E7: paper sections/introduction.tex lines 40-60 [lookup (no check)]
- E8: Lean check of claim 1: accepted [Lean (checks the math itself)]
- E9: Lean check of claim 2: accepted [Lean (checks the math itself)]
- E10: verdict 1: Domain: finite nonempty lattice L with least element 0 (matches) [lookup (no check)]
- E11: verdict 2: Finite algebra (matches) [lookup (no check)]
- E12: verdict 3: Congruences and their order (matches) [lookup (no check)]
- E13: verdict 4: Representability (L ≅ full Con(A)) (matches) [lookup (no check)]
- E14: verdict 5: L-colored complete graph and condition (i) (matches) [lookup (no check)]
- E15: verdict 6: Condition (ii) reflection (matches) [lookup (no check)]
- E16: verdict 7: Admissible placements, Γ_S, condition (iii) connectivity (matches) [lookup (no check)]
- E17: verdict 8: Conclusion: biconditional (matches) [lookup (no check)]
- E18: verdict 9: Remark that conditions are finite checks for fixed |A| (not in the formalization) [lookup (no check)]

(Cost of this audit: $0.4728.)
