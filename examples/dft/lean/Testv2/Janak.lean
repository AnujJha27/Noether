import Testv2.KS
import Mathlib.Analysis.Calculus.Deriv.Basic
import Mathlib.Analysis.Calculus.Deriv.Add
import Mathlib.Analysis.Calculus.Deriv.Comp
import Mathlib.Analysis.Calculus.Deriv.Mul

noncomputable section

variable (X : Type*) [Fintype X]

-- ─────────────────────────────────────────────────────────────────────────────
-- Janak's Theorem  (J.F. Janak, Phys. Rev. B 18, 7165, 1978)
-- ─────────────────────────────────────────────────────────────────────────────

/-- **Janak's Theorem – Single Orbital** (Janak, PRB 18, 7165, 1978)
    The derivative of the orbital energy E_i(f) = f * ⟨φ | H_KS | φ⟩ is ε. -/
theorem janak_single (H_KS : Op X) (φ : H X) (ε : ℝ)
    (hNorm : ‖φ‖ = 1) (hEig : H_KS φ = ε • φ) (f₀ : ℝ) :
    HasDerivAt (fun f => f * @inner ℝ _ _ φ (H_KS φ)) ε f₀ := by
  -- Step 1: ⟨φ|H_KS|φ⟩ = ε is a constant w.r.t. f
  have h_inner : @inner ℝ _ _ φ (H_KS φ) = ε :=
    ks_expectation_eq_eigenvalue X H_KS φ ε hNorm hEig
  simp only [h_inner]
  -- Step 2: d/df [f * ε] = ε  (linear function, slope = ε)
  have hid : HasDerivAt (fun f : ℝ => f) 1 f₀ := hasDerivAt_id f₀
  simpa [one_mul] using hid.mul_const ε

/-- **Janak's Theorem – n-Orbital Form** (Fréchet derivative)
    The Fréchet derivative of E(f) = ⟨ε, f⟩ is the inner product with ε. -/
theorem janak_fderiv (ε : H X) (f₀ : H X) :
    HasFDerivAt (fun f : H X => @inner ℝ _ _ ε f) (innerSL ℝ ε) f₀ :=
  (innerSL ℝ ε).hasFDerivAt

/-- The j-th partial derivative ∂E/∂fⱼ = εⱼ. -/
lemma janak_partial [DecidableEq X] (ε : H X) (j : X) :
    innerSL ℝ ε (EuclideanSpace.single j (1 : ℝ)) = ε j := by
  change @inner ℝ _ _ ε (EuclideanSpace.single j (1 : ℝ)) = ε j
  simp [EuclideanSpace.inner_single_right]

/-- Directional Janak theorem: changing only the `j`-th occupation has slope
    equal to the `j`-th KS eigenvalue. -/
theorem janak_coordinate_deriv [DecidableEq X] (ε f₀ : H X) (j : X) :
    HasDerivAt
      (fun t : ℝ =>
        @inner ℝ _ _ ε (f₀ + t • EuclideanSpace.single j (1 : ℝ)))
      (ε j) 0 := by
  let e_j : H X := EuclideanSpace.single j (1 : ℝ)
  have hcoord : @inner ℝ _ _ ε e_j = ε j := by
    simpa [e_j] using janak_partial X ε j
  have hscalar :
      HasDerivAt
        (fun t : ℝ => @inner ℝ _ _ ε f₀ + t * @inner ℝ _ _ ε e_j)
        (@inner ℝ _ _ ε e_j) 0 := by
    have hlinear :
        HasDerivAt
          (fun t : ℝ => t * @inner ℝ _ _ ε e_j)
          (@inner ℝ _ _ ε e_j) 0 := by
      simpa [one_mul] using
        ((hasDerivAt_id (0 : ℝ)).mul_const (@inner ℝ _ _ ε e_j))
    simpa [add_comm, add_left_comm, add_assoc] using
      hlinear.const_add (@inner ℝ _ _ ε f₀)
  have htarget :
      (fun t : ℝ => @inner ℝ _ _ ε (f₀ + t • e_j))
        =
      (fun t : ℝ => @inner ℝ _ _ ε f₀ + t * @inner ℝ _ _ ε e_j) := by
    funext t
    simp [inner_add_right, real_inner_smul_right]
  rw [show
      (fun t : ℝ =>
        @inner ℝ _ _ ε (f₀ + t • EuclideanSpace.single j (1 : ℝ)))
        =
      (fun t : ℝ => @inner ℝ _ _ ε (f₀ + t • e_j)) by
        funext t
        simp [e_j]]
  rw [htarget]
  simpa [hcoord] using hscalar

end
