/-
A probe that can only "succeed" through a lemma left as `sorry`.

`Shaky n` holds for every `n` (it is `True`), so `probe_untrusted`'s hypothesis is fine.
But `shaky_false`, left as `sorry`, tells `simp` the opposite, so `simp_all` derives `False`
from the hypothesis. Lean's kernel accepts that proof, and it rests on `sorryAx`: no evidence
that the hypotheses contradict each other. The vacuity probe must not report it as a red
flag. The triviality probe is the control: `n = n` really does hold without the hypothesis,
on the standard axioms alone, so that one is a red flag.

Plain Lean, no Mathlib, so both of Scry's Lean versions can read it.
-/

def Shaky (_ : Nat) : Prop := True

@[simp] theorem shaky_false (n : Nat) : Shaky n ↔ False := sorry

theorem probe_untrusted (n : Nat) (h : Shaky n) : n = n := sorry
