## Audit report: `OAI.FiniteCongruence.graph_criterion`

### 1. The paper's claim
This is Theorem "Graph criterion" (`f:criterion`, sections/graph.tex lines 33–50) [E4]:

> "The lattice $L$ is the full congruence lattice of a finite algebra if and only if there is an $L$-colored complete graph $(A,d)$ satisfying all three conditions below. (i) If $p\ne q$, then $d(p,q)\ne0$, and $d(p,q)\le d(p,u)\vee d(u,q)$ … (ii) Whenever $a\not\le b$ in $L$, there are vertices $p,q$ with $d(p,q)\le a$ and $d(p,q)\not\le b$. (iii) For every nonempty edge set $S$, vertices $p,q$ satisfying $d(p,q)\le a_S$ lie in the same connected component of $\Gamma_S$."

- The surrounding setup has $L$ a finite nonempty lattice with least element 0. A colored graph has a finite nonempty vertex set and a symmetric $d$ with $d(p,p)=0$. A placement $f$ is admissible when $d(f p,f q)\le d(p,q)$. $\Gamma_S$ is the graph whose marked adjacencies are the images of edges in $S$ under admissible self-placements [E4].
- A finite algebra is "a nonempty finite set $A$, together with a finite list of total operations of finite nonnegative arity. The list may be empty" (introduction.tex lines 46–49) [E6].

### 2. The formal statement
For every finite type `Lat` with a lattice structure and a bottom element: if there is a graph witness, then `Lat` is representable [E1][E3].
- **Graph witness:** some `size > 0` and a coloring `color : Fin size → Fin size → Lat` such that:
  - the coloring is symmetric;
  - `color l r = ⊥ ↔ l = r`;
  - the triangle inequality holds;
  - the reflection condition holds;
  - for every nonempty finset of ordered pairs `seeds`, `color l r ≤ seeds.sup color` implies `l` and `r` are related by the equivalence closure (`EqvGen`) of "is the image of a seed under an admissible self-map".
- **Representable:** some `size > 0` and an `Algebra (Fin size)` (finitely many operations, each of natural-number arity) whose congruences, ordered by inclusion, are order-isomorphic to `Lat`.
- **Direction:** the statement proves only this one implication. The docstring says "exactly when", but the theorem does not state that.

### 3. Point by point

| Item | Paper says | Lean says | Verdict |
|---|---|---|---|
| Direction of theorem | "if and only if" [E4] | Only `HasGraphWitness → Representable`; the docstring claims "exactly when" [E1][E3] | **Lean concludes less** [E8] |
| The lattice $L$ | Finite nonempty lattice with 0 [E4] | `Fintype`, `Lattice`, `OrderBot` [E1] | matches [E9] |
| Finite algebra and full Con | Nonempty finite carrier; finite, possibly empty, list of operations of arity ≥ 0; $L\cong \mathrm{Con}(A)$ onto [E6] | `Fin size` with `size > 0`, `numOps : ℕ`, arities in ℕ, `Lat ≃o Congruence alg`, where congruences are compatible setoids [E3] | matches [E10] |
| Graph basics and (i) nonzero condition | Finite nonempty $A$, $d$ symmetric, $d(p,p)=0$, $d(p,q)\ne0$ for $p\ne q$ [E4] | `size > 0`; symmetry; `color l r = ⊥ ↔ l = r` [E3] | matches [E11] |
| (i) triangle inequality | $d(p,q)\le d(p,u)\vee d(u,q)$ [E4] | line 45, same [E3] | matches [E12] |
| (ii) reflection | $a\not\le b$ ⇒ ∃ $p,q$ with $d\le a$ and $d\not\le b$ [E4] | lines 46–47, same [E3] | matches [E13] |
| Admissible maps, $\Gamma_S$, (iii) | Unordered edge sets $S$; marked adjacencies are images of $S$ under admissible self-maps; same component [E4] | Ordered-pair `Finset` seeds; `Marked`/`Connected` via `EqvGen`. Symmetry of `color` and of `EqvGen` makes ordered vs unordered pairs irrelevant [E3] | matches [E14] |
| Hypotheses can be met | The one-element lattice comes from the one-vertex graph [E4] | Lean accepts `HasGraphWitness Unit` [E7] | matches [E15] |

### 4. Definitions a person should read closely
- **`graph_criterion` (lines 55–59):** the docstring says "representable … exactly when it has … witness", but the statement is only `→` [E3]. A reader going by the docstring would wrongly think both directions are formalized.
- **`Marked` / `Connected` (lines 32–39):** these encode $\Gamma_S$. Seeds are ordered pairs and connectivity is `Relation.EqvGen`. I judged this equivalent to the paper's unordered graph components, because `color` is symmetric and `EqvGen` is symmetric [E3].
- **`Congruence` and its order (lines 19–23):** the order is the subtype order on `Setoid`, i.e. inclusion of relations. That is the right order for Con(A) [E3].
- **`Algebra` (lines 10–13):** it allows zero operations and nullary operations, as the paper's definition does [E3][E6].

### 5. Lean checks I ran
- **[E7]** `theorem scry_check : HasGraphWitness Unit`, using a one-vertex coloring. Lean accepted it. This shows the hypothesis can be satisfied, in line with the paper's remark about the one-element lattice, so the statement is not vacuous in that case.
- I did not try to check the missing forward direction in Lean; it is simply absent from the statement.

### 6. Overall
Every ingredient matches the paper's definitions: the lattice, the finite algebra, the congruence lattice, admissible placements, $\Gamma_S$, and conditions (i)–(iii). The difference is in the conclusion. The formal statement covers only the sufficiency half of the paper's "if and only if": a graph witness implies representability. It omits the converse, that every representable lattice has such a witness, even though its docstring says "exactly when". The converse is the half the paper's Corollary (semidecidability and witness bounds) also relies on, so the formal result supports only one direction of Theorem `f:criterion`.

## Rows the helper recorded

| Item | Verdict | Affects main result | Lean lines | Evidence |
| --- | --- | --- | --- | --- |
| Direction of the theorem (iff vs one direction) | Lean concludes less | yes | 55-59 | E1, E3, E4 |
| Lattice L: finite nonempty lattice with least element | matches | no | 57-58 | E1, E4 |
| Representability (finite algebra, full congruence lattice) | matches | no | 10-26 | E3, E6 |
| Colored complete graph: finite nonempty vertex set, symmetric d, d(p,p)=0, and (i) d(p,q)≠0 for p≠q | matches | no | 41-53 | E3, E4 |
| Condition (i) triangle inequality | matches | no | 45-45 | E3, E4 |
| Condition (ii) reflection | matches | no | 46-47 | E3, E4 |
| Admissible placements, Γ_S and condition (iii) connectivity | matches | no | 28-50 | E3, E4 |
| Hypotheses are satisfiable (one-element lattice) | matches | no | 52-53 | E7, E4 |

## Evidence

- E1: Lean's reading of the statement of graph_criterion [Lean (checks the math itself)]
- E2: list of paper files [lookup (no check)]
- E3: Lean statement lines 1-63 [lookup (no check)]
- E4: paper sections/graph.tex lines 1-125 [lookup (no check)]
- E5: paper search for 'finite algebra' [lookup (no check)]
- E6: paper sections/introduction.tex lines 40-60 [lookup (no check)]
- E7: Lean check of claim 1: accepted [Lean (checks the math itself)]
- E8: verdict 1: Direction of the theorem (iff vs one direction) (Lean concludes less) [lookup (no check)]
- E9: verdict 2: Lattice L: finite nonempty lattice with least element (matches) [lookup (no check)]
- E10: verdict 3: Representability (finite algebra, full congruence lattice) (matches) [lookup (no check)]
- E11: verdict 4: Colored complete graph: finite nonempty vertex set, symmetric d, d(p,p)=0, and (i) d(p,q)≠0 for p≠q (matches) [lookup (no check)]
- E12: verdict 5: Condition (i) triangle inequality (matches) [lookup (no check)]
- E13: verdict 6: Condition (ii) reflection (matches) [lookup (no check)]
- E14: verdict 7: Admissible placements, Γ_S and condition (iii) connectivity (matches) [lookup (no check)]
- E15: verdict 8: Hypotheses are satisfiable (one-element lattice) (matches) [lookup (no check)]

(Cost of this audit: $0.3975.)
