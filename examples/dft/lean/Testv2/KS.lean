import Mathlib.Analysis.InnerProductSpace.Basic
import Mathlib.Analysis.InnerProductSpace.PiL2
import Mathlib.Analysis.InnerProductSpace.Adjoint
import Mathlib.Analysis.InnerProductSpace.Spectrum
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.Ring

noncomputable section

variable (X : Type*) [Fintype X]

/-- Hilbert space of single-particle states on a spatial grid X. -/
abbrev H := EuclideanSpace ℝ X

/-- Operators on H: bounded continuous linear maps. -/
abbrev Op := H X →L[ℝ] H X

def IsLocal (A : Op X) : Prop :=
  ∃ v : X → ℝ, ∀ (φ : H X) (x : X), (A φ) x = v x * φ x

def IsNonLocal (A : Op X) : Prop :=
  ¬ IsLocal X A

theorem local_not_nonlocal {A : Op X} (hL : IsLocal X A) : ¬ IsNonLocal X A :=
  fun hNL => hNL hL

-- μ_xc: local (diagonal in position space) and self-adjoint (real-valued field)
structure XCPotential where
  op : Op X
  isLocal       : IsLocal X op
  isSelfAdjoint : IsSelfAdjoint op

-- Σ: non-local; treated as self-adjoint in the quasiparticle approximation
-- (Im Σ(E_QP) ≈ 0 for weakly correlated materials — Hybertsen & Louie 1986)
structure SelfEnergy where
  op : Op X
  isNonLocal    : IsNonLocal X op
  isSelfAdjoint : IsSelfAdjoint op

-- C = Σ − μ_xc; expectation values give the eigenvalue gaps Eᵢ − εᵢ
def correction (selfE : SelfEnergy X) (μ : XCPotential X) : Op X :=
  selfE.op - μ.op

-- If C were local via f, then Σ = C + μ would be local via (f+g) — contradiction.
theorem correction_isNonLocal (selfE : SelfEnergy X) (μ : XCPotential X) :
    IsNonLocal X (correction X selfE μ) := by
  intro ⟨f, hf⟩
  apply selfE.isNonLocal
  obtain ⟨g, hg⟩ := μ.isLocal
  refine ⟨fun x => f x + g x, fun φ x => ?_⟩
  have h_split : selfE.op φ = correction X selfE μ φ + μ.op φ := by
    simp [correction, ContinuousLinearMap.sub_apply]
  have h_split_eval : (selfE.op φ) x = (correction X selfE μ φ) x + (μ.op φ) x := by
    rw [h_split]; rfl
  rw [h_split_eval, hf, hg]; ring

-- (A − B)† = A† − B†, so C is self-adjoint whenever Σ and μ_xc are.
theorem correction_isSelfAdjoint (selfE : SelfEnergy X) (μ : XCPotential X) :
    IsSelfAdjoint (correction X selfE μ) := by
  apply IsSelfAdjoint.sub
  · exact selfE.isSelfAdjoint
  · exact μ.isSelfAdjoint

-- ⟨φ, Aψ⟩ = ⟨ψ, Aφ⟩ for self-adjoint A over ℝ
lemma selfAdjoint_inner_symm {A : Op X} (hA : IsSelfAdjoint A) (φ ψ : H X) :
    @inner ℝ _ _ φ (A ψ) = @inner ℝ _ _ ψ (A φ) := by
  rw [← ContinuousLinearMap.adjoint_inner_left]
  rw [hA.adjoint_eq]
  exact real_inner_comm _ _

-- Real polarization identity: ⟨ψ, Aφ⟩ = ¼[⟨φ+ψ, A(φ+ψ)⟩ − ⟨φ−ψ, A(φ−ψ)⟩]
-- (requires self-adjointness to collapse the cross terms)
lemma polarization_selfAdjoint {A : Op X} (hA : IsSelfAdjoint A) (φ ψ : H X) :
    @inner ℝ _ _ ψ (A φ) =
    (1/4 : ℝ) * (@inner ℝ _ _ (φ + ψ) (A (φ + ψ)) -
                  @inner ℝ _ _ (φ - ψ) (A (φ - ψ))) := by
  have expand_plus :
      @inner ℝ _ _ (φ + ψ) (A (φ + ψ)) =
      @inner ℝ _ _ φ (A φ) + @inner ℝ _ _ φ (A ψ) +
      @inner ℝ _ _ ψ (A φ) + @inner ℝ _ _ ψ (A ψ) := by
    rw [map_add, inner_add_left, inner_add_right, inner_add_right]; ring
  have expand_minus :
      @inner ℝ _ _ (φ - ψ) (A (φ - ψ)) =
      @inner ℝ _ _ φ (A φ) - @inner ℝ _ _ φ (A ψ) -
      @inner ℝ _ _ ψ (A φ) + @inner ℝ _ _ ψ (A ψ) := by
    rw [map_sub, inner_sub_left, inner_sub_right, inner_sub_right]; ring
  have sym : @inner ℝ _ _ φ (A ψ) = @inner ℝ _ _ ψ (A φ) :=
    selfAdjoint_inner_symm X hA φ ψ
  rw [expand_plus, expand_minus, sym]; ring

-- Core lemma: self-adjoint A with ⟨φ, Aφ⟩ = 0 for all φ implies A = 0.
-- FALSE without self-adjointness (counterexample: [[0,1],[-1,0]]).
lemma inner_self_zero_of_selfAdj_implies_zero {A : Op X}
    (hA : IsSelfAdjoint A)
    (h : ∀ φ : H X, @inner ℝ _ _ φ (A φ) = (0 : ℝ)) :
    A = 0 := by
  have h_bil : ∀ φ ψ : H X, @inner ℝ _ _ ψ (A φ) = (0 : ℝ) := by
    intro φ ψ
    rw [polarization_selfAdjoint X hA φ ψ, h (φ + ψ), h (φ - ψ)]
    ring
  -- Step 2: Aφ = 0 for all φ, by non-degeneracy of the inner product
  --   Set ψ = Aφ: ⟨Aφ, Aφ⟩ = ‖Aφ‖² = 0, so Aφ = 0.
  have h_zero : ∀ φ : H X, A φ = 0 := by
    intro φ
    have h_norm_sq : @inner ℝ _ _ (A φ) (A φ) = (0 : ℝ) := h_bil φ (A φ)
    rwa [inner_self_eq_zero] at h_norm_sq
  -- Step 3: A = 0 as a continuous linear map (by extensionality)
  ext φ
  simp [h_zero φ]

-- eigenGap(φ) = ⟨φ | Σ − μ_xc | φ⟩ = Eᵢ − εᵢ for orbital φ
def eigenGap (selfE : SelfEnergy X) (μ : XCPotential X) (φ : H X) : ℝ :=
  @inner ℝ _ _ φ (correction X selfE μ φ)

/-- Main theorem: given non-local self-adjoint Σ and local self-adjoint μ_xc,
    ∃ orbital φ with ⟨φ | Σ − μ_xc | φ⟩ ≠ 0. -/
theorem ks_neq_quasiparticle (selfE : SelfEnergy X) (μ : XCPotential X) :
    ∃ φ : H X, eigenGap X selfE μ φ ≠ 0 := by
  by_contra h_all_zero
  push_neg at h_all_zero
  have hC_sa : IsSelfAdjoint (correction X selfE μ) :=
    correction_isSelfAdjoint X selfE μ
  have h_C_zero : correction X selfE μ = 0 :=
    inner_self_zero_of_selfAdj_implies_zero X hC_sa h_all_zero
  have h_eq : selfE.op = μ.op := sub_eq_zero.mp h_C_zero
  exact selfE.isNonLocal (h_eq ▸ μ.isLocal)

-- eigenGap scales quadratically: eigenGap(r • φ) = r² * eigenGap(φ)
private lemma eigenGap_smul (selfE : SelfEnergy X) (μ : XCPotential X) (r : ℝ) (φ : H X) :
    eigenGap X selfE μ (r • φ) = r ^ 2 * eigenGap X selfE μ φ := by
  simp only [eigenGap, correction, map_smul, real_inner_smul_left, real_inner_smul_right]
  ring

/-- Non-uniformity of the eigenvalue correction on the unit sphere: ∃ two unit-norm
    orbitals with distinct ⟨φ|Σ − V_xc|φ⟩ values. -/
theorem correction_nonuniform_on_sphere (selfE : SelfEnergy X) (μ : XCPotential X) :
    ∃ (φ_HOMO φ_LUMO : H X),
      ‖φ_HOMO‖ = 1 ∧ ‖φ_LUMO‖ = 1 ∧
      eigenGap X selfE μ φ_LUMO ≠ eigenGap X selfE μ φ_HOMO := by
  have hC_sa := correction_isSelfAdjoint X selfE μ
  have hC_nl := correction_isNonLocal X selfE μ
  by_contra h
  push_neg at h
  -- h : ∀ φ ψ, ‖φ‖ = 1 → ‖ψ‖ = 1 → eigenGap φ = eigenGap ψ
  -- Get a witness φ₀ with eigenGap(φ₀) ≠ 0 and normalize it to u₀.
  obtain ⟨φ₀, hφ₀⟩ := ks_neq_quasiparticle X selfE μ
  have hφ₀_ne : φ₀ ≠ 0 := fun heq => by simp [heq, eigenGap, correction] at hφ₀
  have hφ₀_pos : 0 < ‖φ₀‖ := norm_pos_iff.mpr hφ₀_ne
  have hφ₀_nz  : ‖φ₀‖ ≠ 0 := hφ₀_pos.ne'
  set u₀ := ‖φ₀‖⁻¹ • φ₀
  have hu₀_norm : ‖u₀‖ = 1 := by
    simp [u₀, norm_smul, inv_mul_cancel₀ hφ₀_nz]
  -- eigenGap(u₀) ≠ 0 (scales by ‖φ₀‖⁻² > 0)
  have hu₀_gap : eigenGap X selfE μ u₀ ≠ 0 := by
    simp only [u₀, eigenGap_smul]
    exact mul_ne_zero (pow_ne_zero _ (ne_of_gt (inv_pos.mpr hφ₀_pos))) hφ₀
  -- All unit vectors give eigenGap = c := eigenGap(u₀)
  set c := eigenGap X selfE μ u₀
  have h_unit : ∀ v : H X, ‖v‖ = 1 → eigenGap X selfE μ v = c :=
    fun v hv => h u₀ v hu₀_norm hv
  -- For ANY v: eigenGap(v) = ‖v‖² * c  (by normalizing v to a unit vector)
  have h_quad : ∀ v : H X, eigenGap X selfE μ v = ‖v‖ ^ 2 * c := by
    intro v
    by_cases hv : v = 0
    · simp [hv, eigenGap, correction]
    · have hv_pos : 0 < ‖v‖ := norm_pos_iff.mpr hv
      have hv_nz : ‖v‖ ≠ 0 := hv_pos.ne'
      have hu : ‖‖v‖⁻¹ • v‖ = 1 := by
        simp [norm_smul, inv_mul_cancel₀ hv_nz]
      have h1 : ‖v‖⁻¹ ^ 2 * eigenGap X selfE μ v = c := by
        rw [← eigenGap_smul]; exact h_unit _ hu
      have hne : ‖v‖⁻¹ ^ 2 ≠ 0 := pow_ne_zero _ (ne_of_gt (inv_pos.mpr hv_pos))
      have heq : eigenGap X selfE μ v = c * ‖v‖ ^ 2 :=
        mul_left_cancel₀ hne (by rw [h1]; field_simp [hv_nz])
      linarith [heq]
  -- ⟨v, (C − c·id)v⟩ = 0 for all v
  have h_zero : ∀ v : H X,
      @inner ℝ _ _ v ((correction X selfE μ - c • ContinuousLinearMap.id ℝ (H X)) v) = 0 := by
    intro v
    have hq : @inner ℝ _ _ v (correction X selfE μ v) = ‖v‖ ^ 2 * c := by
      have := h_quad v; simp only [eigenGap, correction] at this; exact this
    simp only [ContinuousLinearMap.sub_apply, ContinuousLinearMap.smul_apply,
               ContinuousLinearMap.id_apply, inner_sub_right,
               real_inner_smul_right, real_inner_self_eq_norm_sq, hq]
    ring
  -- C − c·id is self-adjoint
  have hD_sa : IsSelfAdjoint (correction X selfE μ - c • ContinuousLinearMap.id ℝ (H X)) := by
    apply IsSelfAdjoint.sub hC_sa
    rw [IsSelfAdjoint, ContinuousLinearMap.star_eq_adjoint]
    have : ContinuousLinearMap.adjoint (c • ContinuousLinearMap.id ℝ (H X)) =
           c • ContinuousLinearMap.id ℝ (H X) := by
      apply ContinuousLinearMap.ext; intro ψ
      apply ext_inner_left ℝ; intro φ
      simp [ContinuousLinearMap.smul_apply,
            ContinuousLinearMap.id_apply, real_inner_smul_right]
    exact this
  -- By core lemma: C − c·id = 0, so C = c·id
  have hD_zero := inner_self_zero_of_selfAdj_implies_zero X hD_sa h_zero
  have hC_eq : correction X selfE μ = c • ContinuousLinearMap.id ℝ (H X) :=
    sub_eq_zero.mp hD_zero
  -- c·id is local, contradicting hC_nl
  apply hC_nl
  refine ⟨fun _ => c, fun φ x => ?_⟩
  have hCφ : correction X selfE μ φ = c • φ := by
    have := DFunLike.congr_fun hC_eq φ
    simp [ContinuousLinearMap.smul_apply, ContinuousLinearMap.id_apply] at this
    exact this
  simp [hCφ, smul_eq_mul]

-- The zero operator is local (constant zero field).
lemma IsLocal_zero : IsLocal X (0 : Op X) :=
  ⟨fun _ => 0, fun φ x => by simp⟩

/-- Operator norm positivity: since Σ − V_xc is non-local, it is nonzero,
    hence has strictly positive operator norm. -/
theorem correction_norm_pos (selfE : SelfEnergy X) (μ : XCPotential X) :
    0 < ‖(correction X selfE μ : Op X)‖ := by
  apply norm_pos_iff.mpr
  intro h_zero
  exact correction_isNonLocal X selfE μ (h_zero ▸ IsLocal_zero X)

/-- For a unit-norm KS eigenstate `φ` of `H_KS` with eigenvalue `ε`,
    the expectation value `⟪φ, H_KS φ⟫` equals `ε`. -/
lemma ks_expectation_eq_eigenvalue (H_KS : Op X) (φ : H X) (ε : ℝ)
    (hNorm : ‖φ‖ = 1) (hEig : H_KS φ = ε • φ) :
    @inner ℝ _ _ φ (H_KS φ) = ε := by
  rw [hEig, real_inner_smul_right, real_inner_self_eq_norm_sq, hNorm]
  ring

-- ─────────────────────────────────────────────────────────────────────────────
-- Fundamental Gap Theorem
-- The KS fundamental gap εᴸ − εᴴ is corrected by ⟨φ_L|C|φ_L⟩ − ⟨φ_H|C|φ_H⟩
-- to give the quasiparticle gap (Hybertsen–Louie, PRB 34, 5390, 1986, Eq. 11)
-- ─────────────────────────────────────────────────────────────────────────────

/-- The Kohn-Sham fundamental gap between HOMO and LUMO KS eigenvalues. -/
def ksGap (ε_HOMO ε_LUMO : ℝ) : ℝ := ε_LUMO - ε_HOMO

/-- The quasiparticle fundamental gap: each KS eigenvalue is shifted by
    its orbital's expectation value of Σ − V_xc.
    E_QP = ε_KS + ⟨φ|Σ(ε_KS) − V_xc|φ⟩  (first-order, static approx.) -/
def qpGap (selfE : SelfEnergy X) (μ : XCPotential X)
    (φ_HOMO φ_LUMO : H X) (ε_HOMO ε_LUMO : ℝ) : ℝ :=
  (ε_LUMO + eigenGap X selfE μ φ_LUMO) - (ε_HOMO + eigenGap X selfE μ φ_HOMO)

-- The QP gap decomposes cleanly into the KS gap plus an orbital-dependent correction.
lemma qpGap_eq_ksGap_add_correction (selfE : SelfEnergy X) (μ : XCPotential X)
    (φ_HOMO φ_LUMO : H X) (ε_HOMO ε_LUMO : ℝ) :
    qpGap X selfE μ φ_HOMO φ_LUMO ε_HOMO ε_LUMO =
    ksGap ε_HOMO ε_LUMO + (eigenGap X selfE μ φ_LUMO - eigenGap X selfE μ φ_HOMO) := by
  simp only [qpGap, ksGap]; ring

/-- Fundamental gap theorem: ∃ unit-norm HOMO and LUMO orbitals for which
    the quasiparticle gap strictly differs from the KS gap. -/
theorem fundamental_gap_ne_ks_gap (selfE : SelfEnergy X) (μ : XCPotential X)
    (ε_HOMO ε_LUMO : ℝ) :
    ∃ (φ_HOMO φ_LUMO : H X),
      ‖φ_HOMO‖ = 1 ∧ ‖φ_LUMO‖ = 1 ∧
      qpGap X selfE μ φ_HOMO φ_LUMO ε_HOMO ε_LUMO ≠ ksGap ε_HOMO ε_LUMO := by
  obtain ⟨φ_H, φ_L, hH, hL, hne⟩ := correction_nonuniform_on_sphere X selfE μ
  refine ⟨φ_H, φ_L, hH, hL, ?_⟩
  rw [qpGap_eq_ksGap_add_correction]
  intro h
  apply hne
  have heq : eigenGap X selfE μ φ_L - eigenGap X selfE μ φ_H = 0 := by linarith
  exact sub_eq_zero.mp heq

/-- **The Underestimation Theorem**
    The Kohn-Sham fundamental gap *strictly underestimates* the quasiparticle gap
    whenever the GW self-energy correction has the physically correct sign. -/
theorem ks_gap_underestimates_qp_gap (selfE : SelfEnergy X) (μ : XCPotential X)
    (φ_HOMO φ_LUMO : H X) (ε_HOMO ε_LUMO : ℝ)
    (h_L : eigenGap X selfE μ φ_LUMO > 0) -- LUMO correction is positive
    (h_H : eigenGap X selfE μ φ_HOMO ≤ 0) : -- HOMO correction is non-positive
    ksGap ε_HOMO ε_LUMO < qpGap X selfE μ φ_HOMO φ_LUMO ε_HOMO ε_LUMO := by
  rw [qpGap_eq_ksGap_add_correction]
  linarith

/-- Spectral decomposition result: Σ − V_xc possesses an orthonormal basis of eigenvectors,
    at least one of which has a strictly non-zero eigenvalue. -/
theorem correction_has_eigenvector (selfE : SelfEnergy X) (μ : XCPotential X) :
    ∃ (φ : H X) (c : ℝ), c ≠ 0 ∧ ‖φ‖ = 1 ∧ correction X selfE μ φ = c • φ := by
  let A : Op X := correction X selfE μ
  have hC_sa : IsSelfAdjoint A := correction_isSelfAdjoint X selfE μ
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
    have h_eig : A_lin φ_i = c_i • φ_i := h_symm.apply_eigenvectorBasis hn i
    have h_eig_Op : A φ_i = c_i • φ_i := h_eig
    exact h_all φ_i c_i h_neq h_norm h_eig_Op

  have hA_lin_zero : A_lin = 0 := by
    apply (h_symm.eigenvectorBasis hn).toBasis.ext
    intro i
    have h_eig := h_symm.apply_eigenvectorBasis hn i
    rw [h_all_zero i] at h_eig
    simp [OrthonormalBasis.coe_toBasis, h_eig]

  have hA_clm_zero : A = 0 := by
    apply ContinuousLinearMap.ext
    intro v
    have h_eq : A v = A_lin v := rfl
    rw [h_eq, hA_lin_zero]
    exact LinearMap.zero_apply v

  have h_A_nz : A ≠ 0 := fun h => (correction_isNonLocal X selfE μ) (by
    have h_corr : correction X selfE μ = 0 := h
    rw [h_corr]
    exact IsLocal_zero X
  )
  exact h_A_nz hA_clm_zero

end
