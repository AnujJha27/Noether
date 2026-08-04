namespace DFTCert.Example

noncomputable section

def canonicalManifestSha256 : String := "{{manifest_sha256}}"

theorem canonicalManifestSha256_bound :
    canonicalManifestSha256 = "{{manifest_sha256}}" := rfl

/-- The reviewed demo topology: a four-site chain.  Three message-passing
    layers expose each endpoint to the other endpoint. -/
def adjacency : Fin 4 → Fin 4 → Prop
  | ⟨0, _⟩, ⟨1, _⟩ => True
  | ⟨1, _⟩, ⟨0, _⟩ => True
  | ⟨1, _⟩, ⟨2, _⟩ => True
  | ⟨2, _⟩, ⟨1, _⟩ => True
  | ⟨2, _⟩, ⟨3, _⟩ => True
  | ⟨3, _⟩, ⟨2, _⟩ => True
  | _, _ => False

def xcEnergy (x : ℝ) : ℝ := if x ≤ 0 then 0 else x

/-- A symmetric residual kernel.  This is a concrete member of the reviewed
    three-hop message-passing architecture class, not a trained-weight claim. -/
def learnedSelfEnergy : Op (Fin 4) :=
  ContinuousLinearMap.id ℝ (H (Fin 4)) + star (ContinuousLinearMap.id ℝ (H (Fin 4)))

end

end DFTCert.Example
