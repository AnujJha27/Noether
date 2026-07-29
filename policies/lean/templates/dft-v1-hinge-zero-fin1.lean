namespace DFTCert.Example

noncomputable section

def canonicalManifestSha256 : String := "{{manifest_sha256}}"

theorem canonicalManifestSha256_bound :
    canonicalManifestSha256 = "{{manifest_sha256}}" := rfl

def xcEnergy (x : ℝ) : ℝ := if x ≤ 0 then 0 else x

def adjacency (_ _ : Fin 1) : Prop := True

def learnedSelfEnergy : Op (Fin 1) := 0

end

end DFTCert.Example
