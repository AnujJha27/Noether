import Mathlib

-- Abstract types for quantum setting
axiom Wavefunc : Type
axiom Density : Type
def Potential : Type := ℝ → ℝ

axiom density_of : Wavefunc → Density
axiom integral : Potential → Density → ℝ
axiom kinetic_interaction : Wavefunc → ℝ
axiom energy_expectation : Wavefunc → Potential → ℝ

axiom energy_def (ψ : Wavefunc) (v : Potential) :
  energy_expectation ψ v = kinetic_interaction ψ + integral v (density_of ψ)

axiom ground_state : Potential → Wavefunc
axiom ground_energy : Potential → ℝ

axiom ground_energy_def (v : Potential) :
  ground_energy v = energy_expectation (ground_state v) v

-- Strict Rayleigh-Ritz: any ψ ≠ ground state has strictly higher energy
axiom rayleigh_ritz_strict (v : Potential) (ψ : Wavefunc) :
  ψ ≠ ground_state v → energy_expectation ψ v > ground_energy v

-- Different potentials (mod constant) yield different ground states
axiom distinct_potentials_distinct_states (v₁ v₂ : Potential) :
  (¬ ∃ c : ℝ, ∀ x, v₁ x = v₂ x + c) → ground_state v₁ ≠ ground_state v₂

-- Integral is linear in potential
axiom integral_diff (v₁ v₂ : Potential) (n : Density) :
  integral v₁ n - integral v₂ n = integral (fun x => v₁ x - v₂ x) n

-- The universal density functional
noncomputable def F (n : Density) : ℝ :=
  sInf (Set.image kinetic_interaction {ψ : Wavefunc | density_of ψ = n})

/-- HK1: Two potentials differing by more than a constant cannot share a ground-state density. -/
theorem Hohenberg_Kohn1
  (v₁ v₂ : Potential)
  (h_distinct : ¬ ∃ c : ℝ, ∀ x, v₁ x = v₂ x + c)
  (h_same_dens : density_of (ground_state v₁) = density_of (ground_state v₂)) :
  False := by
  let ψ₁ := ground_state v₁
  let ψ₂ := ground_state v₂
  have states_distinct : ψ₁ ≠ ψ₂ := distinct_potentials_distinct_states v₁ v₂ h_distinct

  -- Apply strict Rayleigh-Ritz
  have rr₁_strict : energy_expectation ψ₂ v₁ > ground_energy v₁ := by
    apply rayleigh_ritz_strict
    intro h
    exact states_distinct h.symm

  have rr₂_strict : energy_expectation ψ₁ v₂ > ground_energy v₂ := by
    apply rayleigh_ritz_strict
    intro h
    exact states_distinct h

  -- Expand energies using energy_def
  have exp₁ : energy_expectation ψ₂ v₁ = kinetic_interaction ψ₂ + integral v₁ (density_of ψ₂) :=
    energy_def ψ₂ v₁
  have exp₂ : energy_expectation ψ₁ v₂ = kinetic_interaction ψ₁ + integral v₂ (density_of ψ₁) :=
    energy_def ψ₁ v₂
  have e₁ : ground_energy v₁ = kinetic_interaction ψ₁ + integral v₁ (density_of ψ₁) := by
    rw [ground_energy_def, energy_def]
  have e₂ : ground_energy v₂ = kinetic_interaction ψ₂ + integral v₂ (density_of ψ₂) := by
    rw [ground_energy_def, energy_def]
  let n := density_of ψ₁
  have dens_eq : density_of ψ₂ = n := h_same_dens.symm
  rw [dens_eq] at exp₁ e₂
  have ineq₁ : kinetic_interaction ψ₂ + integral v₁ n > kinetic_interaction ψ₁ + integral v₁ n := by
    rw [← exp₁, ← e₁]; exact rr₁_strict
  have ineq₂ : kinetic_interaction ψ₁ + integral v₂ n > kinetic_interaction ψ₂ + integral v₂ n := by
    rw [←exp₂, ←e₂]; exact rr₂_strict

  have E₁_expand : ground_energy v₁ = kinetic_interaction ψ₁ + integral v₁ n := e₁
  have E₂_expand : ground_energy v₂ = kinetic_interaction ψ₂ + integral v₂ n := e₂

  have ineq₁' : ground_energy v₂ > ground_energy v₁ + integral v₂ n - integral v₁ n := by
    rw [E₂_expand]; linarith

  have ineq₂' : ground_energy v₁ > ground_energy v₂ + integral v₁ n - integral v₂ n := by
    rw [E₁_expand]; linarith

  -- Add the inequalities to get a contradiction: E₁ + E₂ > E₁ + E₂
  linarith
