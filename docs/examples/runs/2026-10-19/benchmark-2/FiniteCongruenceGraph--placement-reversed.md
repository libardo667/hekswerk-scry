**Audit report: `OAI.FiniteCongruence.graph_criterion` against the paper's Graph criterion**

## 1. The paper's claim

The claim is Theorem "Graph criterion" (`f:criterion`) in `sections/graph.tex`, lines 33–50 [E4]. It is cited as part (i) of the main theorem in `introduction.tex`, lines 63–64 [E8]:

> "The lattice $L$ is the full congruence lattice of a finite algebra if and only if there is an $L$-colored complete graph $(A,d)$ satisfying all three conditions below. (i) If $p\ne q$, then $d(p,q)\ne0$, and $d(p,q)\le d(p,u)\vee d(u,q)$. (ii) Whenever $a\not\le b$ in $L$, there are vertices $p,q$ with $d(p,q)\le a$ and $d(p,q)\not\le b$. (iii) For every nonempty edge set $S$, vertices $p,q$ satisfying $d(p,q)\le a_S$ lie in the same connected component of $\Gamma_S$."

Here $\Gamma_S$ is built from admissible placements, defined as follows (lines 21–24) [E4]:

> "it is *admissible* if $d'(f(p),f(q))\le d(p,q)$"

So admissible placements are maps that never increase labels. The paper's proof relies on this direction: "Every such translation preserves every congruence, and is therefore an admissible self-placement" [E4].

## 2. The formal statement

For a finite lattice `Lat` with a bottom element, the theorem says [E1, E3]:

- **Left side:** `Lat` is order-isomorphic to the full congruence lattice of some algebra on `Fin size` with `size > 0`. The algebra has finitely many operations, each of finite arity.
- **Right side:** there is a colouring `color : Fin size → Fin size → Lat` with `size > 0` that satisfies all of the following:
  - it is symmetric;
  - `color l r = ⊥ ↔ l = r`;
  - the triangle inequality holds;
  - the reflection condition (ii) holds;
  - for every nonempty finite set of seed pairs, `color l r ≤ sup` implies that `l` and `r` are related by the equivalence closure of `Marked`.

`Marked` uses images of seed edges under maps that satisfy `Admissible`. That definition is:

`Admissible color f := ∀ l r, color l r ≤ color (f l) (f r)` (line 30).

This inequality runs the opposite way from the paper's.

## 3. Point by point

| Item | Paper says | Lean says | Verdict |
|---|---|---|---|
| Lattice hypotheses | Finite nonempty lattice with 0 [E4] | `Fintype`, `Lattice`, `OrderBot` [E1] | matches |
| Representability | Nonempty finite carrier; finite list of finite-arity operations, possibly empty; L ≅ Con(A) [E8] | `Algebra (Fin size)` with `0 < size`; `Lat ≃o Congruence alg` [E3] | matches |
| Graph and conditions (i), (ii) | Symmetric d, d(p,p)=0, nonzero off the diagonal, triangle inequality, reflection [E4] | Same conditions, lines 43–47 [E3] | matches |
| Admissible placement | d(f p, f q) ≤ d(p,q): labels never increase [E4] | color p q ≤ color (f p) (f q): labels never decrease, so such maps are injective [E3, E16] and therefore label-preserving automorphisms | **differs** |
| Connectivity (iii) | Components of Γ_S built from images of S under label-decreasing maps [E4] | Same structure, but only images under automorphisms count, so the condition is strictly stronger [E15] | **differs** |
| Conclusion | Representable ⇔ witness of the paper's kind [E4] | Representable ⇔ witness of the automorphism-only kind [E1] | **differs** |

## 4. Definitions a person should read closely

- **`Admissible` (lines 28–30).** This is the source of the discrepancy. The inequality is reversed relative to the paper.
  - Combined with `color l r = ⊥ ↔ l = r`, any admissible map is injective [E16].
  - On a finite set an injective map is a permutation. A permutation that never decreases labels must preserve them exactly, because some power of it is the identity.
  - So Lean's $\Gamma_S$ uses only the automorphism group of the coloured graph. Constant maps and other non-injective translations are excluded, yet the paper's proof needs them.
- **`IsGraphWitness` (lines 41–50).** Its last clause carries the reversed notion into the connectivity condition.

With this reading, `HasGraphWitness L` amounts to: L is the congruence lattice of a finite set acted on by a permutation group (a G-set). The paper itself says the Pálfy–Pudlák equivalence "does not assert that these two kinds of representation are equivalent for each individual lattice" [E8]. The consequences for each direction of the formal biconditional:

- **← direction:** weaker than the paper's. An automorphism-only witness is also a witness in the paper's sense.
- **→ direction:** claims every representable lattice is the congruence lattice of a G-set. The paper does not claim this, and its proof does not establish it.

## 5. Lean checks I ran

- **[E15], accepted: a coloring that meets the paper's condition (iii) fails Lean's.**
  - The colouring is on 4 vertices with values in ℕ, so it is meant as the 4-element chain 0<1<2<3. The labels are d(0,1)=1, d(0,2)=d(1,2)=2, and every edge touching vertex 3 has label 3.
  - Lean proves this colouring is **not** an `IsGraphWitness`. With seeds {(2,3)}, every map that is admissible in Lean's sense fixes 2 and 3, so 0 is never connected to 3, even though d(0,3) ≤ a_S.
  - In the same check, Lean confirms that the paper-direction map {0,1,2}↦0, 3↦3 does not increase labels. That map sends (2,3) to (0,3), which is exactly the connection the paper's $\Gamma_S$ uses.
  - Caveat: the check used ℕ as the label lattice, because these imports provide no `Lattice` instance for `Fin 4` [E12, E13]. It only exercises the connectivity clause. It shows the definitions differ; it does not refute the theorem, since the 4-chain may have some other automorphism-only witness.
- **[E16], accepted:** under the ⊥-iff-equal clause, every map satisfying Lean's `Admissible` is injective.
- **[E14], accepted:** a sanity check that ℕ has `Lattice` and `OrderBot` instances.
- **[E9]–[E13], rejected:** failed attempts caused by missing imports and instances. They are not evidence about the theorem either way.

## 6. Overall

The objects, domains and conditions (i) and (ii) match the paper. However, the formal statement reverses the inequality in "admissible placement". As a result, its graph witness amounts to the lattice being the congruence lattice of a finite permutation-group action, not of an arbitrary finite algebra. The formal biconditional is therefore not the paper's Graph criterion: its ← direction is weaker than the paper's, and its → direction is a per-lattice claim that the paper neither makes nor proves.

## Rows the helper recorded

| Item | Verdict | Affects main result | Lean lines | Evidence |
| --- | --- | --- | --- | --- |
| Admissible placement (direction of inequality) | differs | yes | 28-30 | E3, E4, E16, E15 |
| Connectivity condition (iii) via Marked/Connected | differs | yes | 32-50 | E3, E4, E15 |
| Representability (finite algebra, full congruence lattice) | matches | no | 10-26 | E3, E8 |
| Lattice hypotheses | matches | no | 57-58 | E1, E4 |
| Coloured complete graph, condition (i), condition (ii) | matches | no | 41-53 | E3, E4 |
| Conclusion (biconditional) | differs | yes | 57-58 | E1, E4, E8, E15, E16 |

## Evidence

- E1: Lean's reading of the statement of graph_criterion [Lean (checks the math itself)]
- E2: list of paper files [lookup (no check)]
- E3: Lean statement lines 1-63 [lookup (no check)]
- E4: paper sections/graph.tex lines 1-125 [lookup (no check)]
- E5: paper search for 'permutation' [lookup (no check)]
- E6: paper search for 'admissible' [lookup (no check)]
- E7: paper search for 'finite algebra' [lookup (no check)]
- E8: paper sections/introduction.tex lines 1-70 [lookup (no check)]
- E9: Lean check of claim 1: not accepted [Lean (checks the math itself)]
- E10: Lean check of claim 2: not accepted [Lean (checks the math itself)]
- E11: Lean check of claim 3: not accepted [Lean (checks the math itself)]
- E12: Lean check of claim 4: not accepted [Lean (checks the math itself)]
- E13: Lean check of claim 5: not accepted [Lean (checks the math itself)]
- E14: Lean check of claim 6: accepted [Lean (checks the math itself)]
- E15: Lean check of claim 7: accepted [Lean (checks the math itself)]
- E16: Lean check of claim 8: accepted [Lean (checks the math itself)]
- E17: verdict 1: Admissible placement (direction of inequality) (differs) [lookup (no check)]
- E18: verdict 2: Connectivity condition (iii) via Marked/Connected (differs) [lookup (no check)]
- E19: verdict 3: Representability (finite algebra, full congruence lattice) (matches) [lookup (no check)]
- E20: verdict 4: Lattice hypotheses (matches) [lookup (no check)]
- E21: verdict 5: Coloured complete graph, condition (i), condition (ii) (matches) [lookup (no check)]
- E22: verdict 6: Conclusion (biconditional) (differs) [lookup (no check)]

(Cost of this audit: $1.9480.)
