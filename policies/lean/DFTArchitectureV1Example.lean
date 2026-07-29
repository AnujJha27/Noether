import Testv2.Verifier
import Mathlib.Tactic

/-! A concrete, proof-bearing example for the configurable DFT V1 policy. -/

namespace DFTCert.Example

noncomputable section

def canonicalManifestSha256 : String :=
  "56aa38761aaf0615df247d014202da86dbbd8aee7e9a20bc92785431303d4f92"

theorem canonicalManifestSha256_bound :
    canonicalManifestSha256 =
      "56aa38761aaf0615df247d014202da86dbbd8aee7e9a20bc92785431303d4f92" := rfl

/-- A continuous hinge with distinct one-sided derivatives at zero. -/
def xcEnergy (x : ℝ) : ℝ := if x ≤ 0 then 0 else x

lemma xcEnergy_hasLeftDeriv : HasLeftDeriv xcEnergy 0 0 := by
  unfold HasLeftDeriv
  apply (hasDerivAt_const (x := 0) (c := (0 : ℝ))).hasDerivWithinAt.congr
  · intro x hx
    simp [xcEnergy, hx]
  · simp [xcEnergy]

lemma xcEnergy_hasRightDeriv : HasRightDeriv xcEnergy 0 1 := by
  unfold HasRightDeriv
  apply (hasDerivAt_id (𝕜 := ℝ) 0).hasDerivWithinAt.congr
  · intro x hx
    rcases hx.eq_or_lt with rfl | hx
    · simp [xcEnergy]
    · simp [xcEnergy, not_le.mpr hx]
  · simp [xcEnergy]

def xcCertificate : XCDiscontinuityCertificate xcEnergy where
  electronNumber := 0
  leftSlope := 0
  rightSlope := 1
  hasLeftDeriv := xcEnergy_hasLeftDeriv
  hasRightDeriv := xcEnergy_hasRightDeriv
  discontinuity_ne_zero := by norm_num [xcDiscontinuity]

def adjacency (_ _ : Fin 1) : Prop := True

def learnedSelfEnergy : Op (Fin 1) := 0

lemma learnedSelfEnergy_isKLocal :
    IsKLocal (Fin 1) adjacency 0 learnedSelfEnergy := by
  intro φ ψ x hAgreement
  rfl

lemma learnedSelfEnergy_isSelfAdjoint : IsSelfAdjoint learnedSelfEnergy := by
  exact IsSelfAdjoint.zero _

def manifest : ArchitectureManifest (Fin 1) where
  name := "example-proof-bearing-model"
  xcEnergy := xcEnergy
  xcCertificate := xcCertificate
  adjacency := adjacency
  receptiveField := 0
  learnedSelfEnergy := learnedSelfEnergy
  isKLocal := learnedSelfEnergy_isKLocal
  isSelfAdjoint := learnedSelfEnergy_isSelfAdjoint
  requiredCouplings := []

theorem certificate : (verify (Fin 1) manifest).approved = true := by
  exact verify_approved (Fin 1) manifest

end

end DFTCert.Example
