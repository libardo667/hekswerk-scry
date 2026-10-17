import Mathlib.Tactic

/-! Statements with known answers for Scry's statement probes. -/

/-- Vacuous: no natural number is both below 2 and above 5, so this says nothing. -/
theorem probe_vacuous (n : ℕ) (h₁ : n < 2) (h₂ : 5 < n) : n = 42 := by omega

/-- Trivial: the conclusion holds for every real number; the hypothesis is not needed. -/
theorem probe_trivial (x : ℝ) (_h : 100 < x) : 0 ≤ x ^ 2 + 1 := by positivity

/-- Neither: the hypothesis is satisfiable and needed. -/
theorem probe_honest (x : ℝ) (h : 1 < x) : 0 < x - 1 := by linarith
