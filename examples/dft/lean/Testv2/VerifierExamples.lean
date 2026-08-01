import Testv2.Verifier
import Mathlib.Tactic

/-! Compilation examples for the verifier's two rejection mechanisms. -/

noncomputable section

/-- The identity functional is differentiable, so its left and right slopes
    cannot form an XC derivative discontinuity. -/
example (N : ℝ) : xcDiscontinuity 1 1 = 0 := by
  apply differentiableAt_forces_zero_xcDiscontinuity (fun x : ℝ => x) N 1 1 1
  · exact hasDerivAt_id N
  · exact (hasDerivAt_id N).hasDerivWithinAt
  · exact (hasDerivAt_id N).hasDerivWithinAt

/-- A two-node graph where node 1 is not visible from node 0 at zero hops. -/
def twoNodeAdj : Fin 2 → Fin 2 → Prop
  | ⟨0, _⟩, ⟨1, _⟩ => True
  | ⟨1, _⟩, ⟨0, _⟩ => True
  | _, _ => False

example : ¬ KNbhd twoNodeAdj 0 ⟨0, by omega⟩ ⟨1, by omega⟩ := by
  rintro ⟨m, hm, hReach⟩
  have hm0 : m = 0 := Nat.eq_zero_of_le_zero hm
  subst m
  simpa using hReach
