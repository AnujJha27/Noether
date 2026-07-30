namespace ProofSearch.PhysicsToy

/-!
Small physics-flavored Lean targets for Noether demos.

These are intentionally dependency-light and bundled with the repository. They
are not meant to be a physics library. Their job is to give the orchestrator
real-looking theorem statements with stable targets, binder contexts, products,
records, and rewrite/constructor structure.
-/

structure ToyState where
  energy : Int
  momentum : Int
  charge : Int
deriving Repr, BEq

def identityEvolution (state : ToyState) : ToyState := state

def reverseMomentum (state : ToyState) : ToyState :=
  { state with momentum := -state.momentum }

def combine (left right : ToyState) : ToyState :=
  {
    energy := left.energy + right.energy
    momentum := left.momentum + right.momentum
    charge := left.charge + right.charge
  }

structure ConservationLaw (evolve : ToyState → ToyState) where
  energy_conserved : ∀ state, (evolve state).energy = state.energy
  charge_conserved : ∀ state, (evolve state).charge = state.charge

theorem identity_energy_conserved (state : ToyState) :
    (identityEvolution state).energy = state.energy := by
  rfl

theorem identity_charge_conserved (state : ToyState) :
    (identityEvolution state).charge = state.charge := by
  rfl

theorem identity_conservation_law :
    ConservationLaw identityEvolution := by
  constructor
  · intro state
    rfl
  · intro state
    rfl

theorem reverse_momentum_energy_conserved (state : ToyState) :
    (reverseMomentum state).energy = state.energy := by
  rfl

theorem reverse_momentum_is_involution (state : ToyState) :
    reverseMomentum (reverseMomentum state) = state := by
  cases state
  simp [reverseMomentum]

theorem combine_energy_projection (left right : ToyState) :
    (combine left right).energy = left.energy + right.energy := by
  rfl

theorem combine_charge_projection (left right : ToyState) :
    (combine left right).charge = left.charge + right.charge := by
  rfl

theorem combine_zero_right_energy (state : ToyState) :
    (combine state { energy := 0, momentum := 0, charge := 0 }).energy = state.energy := by
  simp [combine]

end ProofSearch.PhysicsToy
