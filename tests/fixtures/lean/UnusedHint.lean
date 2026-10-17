import Mathlib.Tactic

theorem unused_hint (x : ℝ) (hx : 0 < x) : 0 < x + 1 := by
  have h : 0 < x + 1 := by
    linarith [(by norm_num : (0 : ℝ) < 2)]
  exact h
