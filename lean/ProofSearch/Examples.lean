namespace ProofSearch.Examples

theorem add_zero (n : Nat) : n + 0 = n := by
  rfl

theorem and_swap (p q : Prop) : p ∧ q → q ∧ p := by
  intro h
  exact ⟨h.2, h.1⟩

universe u

theorem identity {α : Sort u} (x : α) : x = x := by
  rfl

end ProofSearch.Examples
