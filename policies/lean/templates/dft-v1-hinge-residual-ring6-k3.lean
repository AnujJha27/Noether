namespace DFTCert.Example

noncomputable section

def canonicalManifestSha256 : String := "{{manifest_sha256}}"

theorem canonicalManifestSha256_bound :
    canonicalManifestSha256 = "{{manifest_sha256}}" := rfl

/-- Six-site molecular ring.  Its antipodal sites 0 and 3 are three hops apart. -/
def adjacency : Fin 6 → Fin 6 → Prop
  | ⟨0, _⟩, ⟨1, _⟩ => True | ⟨1, _⟩, ⟨0, _⟩ => True
  | ⟨1, _⟩, ⟨2, _⟩ => True | ⟨2, _⟩, ⟨1, _⟩ => True
  | ⟨2, _⟩, ⟨3, _⟩ => True | ⟨3, _⟩, ⟨2, _⟩ => True
  | ⟨3, _⟩, ⟨4, _⟩ => True | ⟨4, _⟩, ⟨3, _⟩ => True
  | ⟨4, _⟩, ⟨5, _⟩ => True | ⟨5, _⟩, ⟨4, _⟩ => True
  | ⟨5, _⟩, ⟨0, _⟩ => True | ⟨0, _⟩, ⟨5, _⟩ => True
  | _, _ => False

def xcEnergy (x : ℝ) : ℝ := if x ≤ 0 then 0 else x

/-- Symmetric residual kernel in the reviewed three-hop GNN class. -/
def learnedSelfEnergy : Op (Fin 6) :=
  ContinuousLinearMap.id ℝ (H (Fin 6)) + star (ContinuousLinearMap.id ℝ (H (Fin 6)))

end

end DFTCert.Example
