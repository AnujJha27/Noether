import Testv2.KS

/-!
# Spatial-receptive-field contracts for learned operators

These definitions move the reusable architecture checks out of the demo
sandbox and into the `Testv2` physics surface.
-/

noncomputable section

/-- Exact path reachability through an adjacency relation. -/
def KReach {V : Type*} (adj : V → V → Prop) : ℕ → V → V → Prop
  | 0, x, y => x = y
  | n + 1, x, y => ∃ z, KReach adj n x z ∧ adj z y

@[simp] lemma KReach_zero {V : Type*} {adj : V → V → Prop} {x y : V} :
    KReach adj 0 x y ↔ x = y := Iff.rfl

@[simp] lemma KReach_succ {V : Type*} {adj : V → V → Prop} {n : ℕ} {x y : V} :
    KReach adj (n + 1) x y ↔ ∃ z, KReach adj n x z ∧ adj z y := Iff.rfl

/-- Reachability within at most `k` message-passing hops. -/
def KNbhd {V : Type*} (adj : V → V → Prop) (k : ℕ) (x y : V) : Prop :=
  ∃ m ≤ k, KReach adj m x y

/-- A linear operator is k-local when its output at `x` depends only on input
    values within `k` graph hops of `x`. -/
def IsKLocal (X : Type*) [Fintype X] (adj : X → X → Prop) (k : ℕ)
    (A : Op X) : Prop :=
  ∀ (φ ψ : H X) (x : X),
    (∀ y : X, KNbhd adj k x y → φ y = ψ y) →
    (A φ) x = (A ψ) x

/-- Delta probe at a spatial grid point. -/
def stdBasis (X : Type*) [Fintype X] [DecidableEq X] (j : X) : H X :=
  EuclideanSpace.single j (1 : ℝ)

lemma stdBasis_of_ne (X : Type*) [Fintype X] [DecidableEq X]
    (i j : X) (h : i ≠ j) : stdBasis X j i = (0 : ℝ) := by
  simp [stdBasis, h]

/-- A k-local learned operator cannot equal a reference self-energy having a
    nonzero coupling beyond its receptive field. -/
theorem klocal_gap (X : Type*) [Fintype X] [DecidableEq X]
    (adj : X → X → Prop) (k : ℕ)
    (selfE : SelfEnergy X) (ml_op : Op X)
    (hKLocal : IsKLocal X adj k ml_op)
    (x y : X)
    (hNoReach : ¬ KNbhd adj k x y)
    (hCoupling : (selfE.op (stdBasis X y)) x ≠ 0) :
    ml_op ≠ selfE.op := by
  intro hEq
  apply hCoupling
  rw [← hEq]
  have hAgree : ∀ z : X, KNbhd adj k x z → (stdBasis X y : H X) z = (0 : H X) z := by
    intro z hz
    have hzy : z ≠ y := by
      intro hzy
      apply hNoReach
      rcases hz with ⟨m, hm, hPath⟩
      exact ⟨m, hm, hzy ▸ hPath⟩
    exact stdBasis_of_ne X z y hzy
  have hZero : (ml_op (stdBasis X y)) x = (ml_op 0) x :=
    hKLocal (stdBasis X y) 0 x hAgree
  simpa using hZero

