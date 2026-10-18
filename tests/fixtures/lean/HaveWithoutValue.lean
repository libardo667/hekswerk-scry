import Mathlib.Tactic

theorem have_without_value (n : ℕ) (hn : 0 < n) : 0 < n + 1 := by
  have h : 0 < n
  · exact hn
  exact Nat.lt_succ_of_lt h
