namespace DFTCert.Example

noncomputable section

def xcCertificate : XCDiscontinuityCertificate xcEnergy :=
  Classical.choice generated_xc_discontinuity

def manifest : ArchitectureManifest (Fin 1) where
  name := "{{model_name}}"
  xcEnergy := xcEnergy
  xcCertificate := xcCertificate
  adjacency := adjacency
  receptiveField := 0
  learnedSelfEnergy := learnedSelfEnergy
  isKLocal := generated_spatial_coverage
  isSelfAdjoint := generated_self_adjoint
  requiredCouplings := []

theorem certificate : (verify (Fin 1) manifest).approved = true := by
  exact verify_approved (Fin 1) manifest

end

end DFTCert.Example
