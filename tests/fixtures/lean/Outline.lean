/-
An outline's test project. `result` rests on everything below; each piece is here to test
one rule of `ScryExport/Outline.lean`:

* `Pt` derives `DecidableEq`. The instance and the constructor's helpers are made by Lean,
  not written by a person, so `pts_differ` (proved by `decide`) is outlined as using `Pt`
  itself, and nothing Lean made appears as a part.
* `double` is private. It is a part, shown by the name its author wrote.
* `Loose` hides a hypothesis inside a definition. `loose` never uses it, but it is the
  definition's hypothesis, not the theorem's statement's, so it is not reported.
* `result` takes `_spare`, and, nested under `∧`, `∃` and `∀`, a hypothesis `m ≠ 3`; its
  proof uses neither. Its other hypotheses are used.

Plain Lean, no Mathlib, so both of Scry's Lean versions can outline it.
-/

namespace OutlineExample

/-- A point with two whole-number coordinates. -/
structure Pt where
  x : Nat
  y : Nat
  deriving DecidableEq

def swap (p : Pt) : Pt := ⟨p.y, p.x⟩

private def double (n : Nat) : Nat := n + n

def parity : Nat → Bool
  | 0 => true
  | n + 1 => !parity n

def Loose (n : Nat) : Prop := ∀ m, m < n → m ≤ m

theorem loose (n : Nat) : Loose n := fun m _ => Nat.le_refl m

theorem swap_swap (p : Pt) : swap (swap p) = p := by
  cases p
  rfl

theorem double_eq (n : Nat) : double n = 2 * n := by
  unfold double
  omega

theorem pts_differ : (⟨1, 2⟩ : Pt) ≠ ⟨2, 1⟩ := by decide

theorem result : ∀ n : Nat, 0 < n → (_spare : n ≠ 7) →
    (∃ k, k < n ∧ double k = 2 * k ∧ ∀ m, m < n → m ≠ 3 → m ≤ n) ∧
    swap (swap ⟨n, n⟩) = ⟨n, n⟩ ∧ Loose n ∧ parity 0 = true ∧ (⟨1, 2⟩ : Pt) ≠ ⟨2, 1⟩ := by
  intro n h _spare
  exact ⟨⟨0, h, double_eq 0, fun m hm _ => Nat.le_of_lt hm⟩, swap_swap _, loose n, rfl,
    pts_differ⟩

end OutlineExample
