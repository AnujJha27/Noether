import Mathlib.Analysis.InnerProductSpace.Spectrum
import Mathlib.Analysis.InnerProductSpace.Adjoint
import Mathlib.Analysis.InnerProductSpace.PiL2
import Mathlib.Analysis.InnerProductSpace.Positive

variable (X : Type*) [Fintype X]

abbrev H := EuclideanSpace ℝ X
abbrev Op := H X →L[ℝ] H X

open LinearMap

theorem correction_has_eigenvector (selfE : Op X) (μ : Op X) 
    (A : Op X) (hC_sa : IsSelfAdjoint A) (h_A_nz : A ≠ 0) :
    ∃ (φ : H X) (c : ℝ), c ≠ 0 ∧ ‖φ‖ = 1 ∧ A φ = c • φ := by
  let A_lin : H X →ₗ[ℝ] H X := A
  have h_symm : A_lin.IsSymmetric := hC_sa.isSymmetric
  let n := Module.finrank ℝ (H X)
  have hn : Module.finrank ℝ (H X) = n := rfl

  by_contra h_all
  push_neg at h_all

  have h_all_zero : ∀ i : Fin n, h_symm.eigenvalues hn i = 0 := by
    intro i
    let c_i := h_symm.eigenvalues hn i
    let φ_i := h_symm.eigenvectorBasis hn i
    by_contra h_neq
    have h_norm : ‖φ_i‖ = 1 := (h_symm.eigenvectorBasis hn).orthonormal.1 i
    have h_eig : A_lin φ_i = c_i • φ_i := IsSymmetric.apply_eigenvectorBasis h_symm hn i
    have h_eig_Op : A φ_i = c_i • φ_i := h_eig
    exact h_all φ_i c_i h_neq h_norm h_eig_Op

  have hA_lin_zero : A_lin = 0 := by
    ext v
    have h_repr_zero : (h_symm.eigenvectorBasis hn).repr (A_lin v) = 0 := by
      ext i
      have h_step := IsSymmetric.eigenvectorBasis_apply_self_apply h_symm hn v i
      have h_zero_mul : h_symm.eigenvalues hn i * ((h_symm.eigenvectorBasis hn).repr v) i = 0 := by
        rw [h_all_zero i, MulZeroClass.zero_mul]
      exact Eq.trans h_step h_zero_mul
    calc A_lin v
      _ = (h_symm.eigenvectorBasis hn).repr.symm ((h_symm.eigenvectorBasis hn).repr (A_lin v)) := by rw [LinearEquiv.symm_apply_apply]
      _ = (h_symm.eigenvectorBasis hn).repr.symm 0 := by rw [h_repr_zero]
      _ = 0 := map_zero _

  have hA_clm_zero : A = 0 := by
    apply ContinuousLinearMap.ext
    intro v
    have h_eq : A v = A_lin v := rfl
    rw [h_eq, hA_lin_zero]
    exact LinearMap.zero_apply v

  exact h_A_nz hA_clm_zero
