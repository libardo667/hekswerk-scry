import Mathlib.Tactic

/-!
# A fraction that never reaches 1

Scry's bundled example: for `x ≥ 0`, the fraction `x / (x + 7)` is never `1`.
The proof deliberately takes the long way round to show `x + 7 > 0`, going
through cubes and squares, the way machine-written proofs often do.
-/

theorem shifted_fraction_ne_one (x : ℝ) (hx : x ≥ 0) : x / (x + 7) ≠ 1 := by
  have cube_pos : (x + 7) ^ 3 > 0 := pow_pos (by linarith) 3
  have cube_split : (x + 7) ^ 3 = (x + 7) * (x + 7) ^ 2 := by ring
  have sq_pos : (x + 7) ^ 2 > 0 := pow_pos (by linarith) 2
  have shift_pos : x + 7 > 0 := by
    rw [cube_split] at cube_pos
    exact pos_of_mul_pos_left cube_pos (le_of_lt sq_pos)
  have sq_nonneg_x : x ^ 2 ≥ 0 := sq_nonneg x
  have lt_shift : x < x + 7 := by linarith
  have below_one : x / (x + 7) < 1 := (div_lt_one shift_pos).mpr lt_shift
  exact ne_of_lt below_one
