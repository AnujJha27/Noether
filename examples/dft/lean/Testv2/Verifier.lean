import Testv2.XC
import Testv2.Spatial

/-!
# Pre-training verifier contracts

A successful certificate means that the supplied architecture satisfies the
declared structural physics obligations.  It is not a claim about numerical
accuracy or trained weights.
-/

noncomputable section

variable (X : Type*) [Fintype X] [DecidableEq X]

/-- A physically required dependency of the learned self-energy.  V1 keeps
    these explicit: they come from a domain expert or a separately formalized
    reference model, never from the training data. -/
structure CouplingRequirement (adj : X → X → Prop) (receptiveField : ℕ) where
  outputSite : X
  inputSite : X
  covered : KNbhd adj receptiveField outputSite inputSite

/-- The formal, Lean-native counterpart of the architecture manifest. -/
structure ArchitectureManifest where
  name : String
  xcEnergy : ℝ → ℝ
  xcCertificate : XCDiscontinuityCertificate xcEnergy
  adjacency : X → X → Prop
  receptiveField : ℕ
  learnedSelfEnergy : Op X
  isKLocal : IsKLocal X adjacency receptiveField learnedSelfEnergy
  isSelfAdjoint : IsSelfAdjoint learnedSelfEnergy
  requiredCouplings : List (CouplingRequirement X adjacency receptiveField)

/-- A concise, serializable result produced only after all obligations have
    been checked by Lean. -/
structure VerificationReport where
  name : String
  xcVerified : Bool
  spatialCoverageVerified : Bool
  selfAdjointVerified : Bool
  approved : Bool

def VerificationReport.toJson (report : VerificationReport) : String :=
  "{\"name\":\"" ++ report.name ++ "\",\"xc_verified\":" ++
  toString report.xcVerified ++ ",\"spatial_coverage_verified\":" ++
  toString report.spatialCoverageVerified ++ ",\"self_adjoint_verified\":" ++
  toString report.selfAdjointVerified ++ ",\"approved\":" ++
  toString report.approved ++ "}"

/-- Constructing a manifest requires all positive proofs.  Therefore its
    report is an unambiguous pre-training approval. -/
def verify (manifest : ArchitectureManifest X) : VerificationReport :=
  { name := manifest.name
    xcVerified := true
    spatialCoverageVerified := true
    selfAdjointVerified := true
    approved := true }

theorem verify_approved (manifest : ArchitectureManifest X) :
    (verify X manifest).approved = true := rfl

/-- A missing reachability proof is a genuine blocker: together with a
    nonzero reference coupling, `klocal_gap` proves the learned operator
    cannot equal the reference self-energy. -/
theorem uncovered_requirement_blocks
    (adj : X → X → Prop) (receptiveField : ℕ)
    (selfE : SelfEnergy X) (ml : Op X)
    (hKLocal : IsKLocal X adj receptiveField ml)
    (outputSite inputSite : X)
    (hUncovered : ¬ KNbhd adj receptiveField outputSite inputSite)
    (hReferenceCoupling : (selfE.op (stdBasis X inputSite)) outputSite ≠ 0) :
    ml ≠ selfE.op :=
  klocal_gap X adj receptiveField selfE ml hKLocal outputSite inputSite
    hUncovered hReferenceCoupling

