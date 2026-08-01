import Mathlib.Analysis.Calculus.Deriv.Basic

/-!
# Exchange-correlation derivative discontinuity

The derivative discontinuity at an integer electron number is a jump between
the one-sided derivatives of an energy functional.  This deliberately does
not use continuity: a continuous function can still have a derivative jump.
-/

noncomputable section

/-- `d` is the left derivative of `E` at electron number `N`. -/
def HasLeftDeriv (E : ℝ → ℝ) (N d : ℝ) : Prop :=
  HasDerivWithinAt E d (Set.Iic N) N

/-- `d` is the right derivative of `E` at electron number `N`. -/
def HasRightDeriv (E : ℝ → ℝ) (N d : ℝ) : Prop :=
  HasDerivWithinAt E d (Set.Ici N) N

/-- The exchange-correlation derivative discontinuity. -/
def xcDiscontinuity (leftSlope rightSlope : ℝ) : ℝ := rightSlope - leftSlope

/-- Formal evidence that a functional has a physically relevant derivative
    discontinuity at an electron-number boundary. -/
structure XCDiscontinuityCertificate (E : ℝ → ℝ) where
  electronNumber : ℝ
  leftSlope : ℝ
  rightSlope : ℝ
  hasLeftDeriv : HasLeftDeriv E electronNumber leftSlope
  hasRightDeriv : HasRightDeriv E electronNumber rightSlope
  discontinuity_ne_zero : xcDiscontinuity leftSlope rightSlope ≠ 0

/-- A differentiable functional has the same left and right derivative at a
    boundary, and hence cannot carry a derivative discontinuity there. -/
theorem differentiableAt_forces_zero_xcDiscontinuity
    (E : ℝ → ℝ) (N d leftSlope rightSlope : ℝ)
    (hDiff : HasDerivAt E d N)
    (hLeft : HasLeftDeriv E N leftSlope)
    (hRight : HasRightDeriv E N rightSlope) :
    xcDiscontinuity leftSlope rightSlope = 0 := by
  have hLeftEq : leftSlope = d := by
    symm
    have h :=
      (uniqueDiffOn_Iic N).eq (by simp : N ∈ Set.Iic N) hDiff.hasDerivWithinAt hLeft
    simpa using congrArg (fun D : ℝ →L[ℝ] ℝ => D 1) h
  have hRightEq : rightSlope = d := by
    symm
    have h :=
      (uniqueDiffOn_Ici N).eq (by simp : N ∈ Set.Ici N) hDiff.hasDerivWithinAt hRight
    simpa using congrArg (fun D : ℝ →L[ℝ] ℝ => D 1) h
  simp [xcDiscontinuity, hLeftEq, hRightEq]

/-- No certificate with a nonzero derivative discontinuity can be built for a
    functional differentiable at the certified electron number. -/
theorem differentiableAt_rejects_xc_certificate
    (E : ℝ → ℝ) (certificate : XCDiscontinuityCertificate E)
    (d : ℝ) (hDiff : HasDerivAt E d certificate.electronNumber) : False := by
  apply certificate.discontinuity_ne_zero
  exact differentiableAt_forces_zero_xcDiscontinuity E certificate.electronNumber d
    certificate.leftSlope certificate.rightSlope hDiff
    certificate.hasLeftDeriv certificate.hasRightDeriv
