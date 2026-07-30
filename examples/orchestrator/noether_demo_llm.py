#!/usr/bin/env python3
"""Deterministic demo adapter for Noether examples.

This is not an LLM. It implements the same JSON stdin/stdout contract as a
model adapter so the agentic harness can be demonstrated reproducibly.
"""

from __future__ import annotations

import json
import sys


XC_PATCH = """by
  refine ⟨{
    electronNumber := 0
    leftSlope := 0
    rightSlope := 1
    hasLeftDeriv := ?_
    hasRightDeriv := ?_
    discontinuity_ne_zero := by norm_num [xcDiscontinuity]
  }⟩
  · unfold HasLeftDeriv
    apply (hasDerivAt_const (x := 0) (c := (0 : ℝ))).hasDerivWithinAt.congr
    · intro x hx
      simp [DFTCert.Example.xcEnergy, hx]
    · simp [DFTCert.Example.xcEnergy]
  · unfold HasRightDeriv
    apply (hasDerivAt_id (𝕜 := ℝ) 0).hasDerivWithinAt.congr
    · intro x hx
      rcases hx.eq_or_lt with rfl | hx
      · simp [DFTCert.Example.xcEnergy]
      · simp [DFTCert.Example.xcEnergy, not_le.mpr hx]
    · simp [DFTCert.Example.xcEnergy]"""


PATCHES = [
    ("generated_xc_discontinuity", XC_PATCH, "construct the reviewed XC discontinuity certificate"),
    ("generated_spatial_coverage", "by\n  intro φ ψ x hAgreement\n  rfl", "zero Fin 1 operator is definitionally local"),
    ("generated_self_adjoint", "by\n  exact IsSelfAdjoint.zero _", "use the reviewed zero-operator self-adjoint lemma"),
    ("ConservationLaw ProofSearch.PhysicsToy.identityEvolution", "by\n  constructor\n  · intro state\n    rfl\n  · intro state\n    rfl", "construct the conservation-law record"),
    ("reverseMomentum (ProofSearch.PhysicsToy.reverseMomentum state) = state", "by\n  cases state\n  simp [ProofSearch.PhysicsToy.reverseMomentum]", "split the toy state record and reduce record updates"),
    ("combine state { energy := 0, momentum := 0, charge := 0 }", "by\n  simp [ProofSearch.PhysicsToy.combine]", "unfold combine and simplify addition by zero"),
    ("combine left right", "by\n  rfl", "record projection is definitional"),
    ("identityEvolution state", "by\n  rfl", "identity evolution is definitional"),
]


def candidate_for(prompt: str) -> dict[str, str]:
    for needle, patch, rationale in PATCHES:
        if needle in prompt:
            return {
                "patch": patch,
                "rationale": rationale,
                "progress_summary": rationale,
            }
    return {
        "patch": "by\n  rfl",
        "rationale": "fallback definitional proof for bundled examples",
        "progress_summary": "fallback rfl",
    }


def decomposition_for(prompt: str) -> dict[str, object]:
    theorem = ""
    for line in prompt.splitlines():
        if line.startswith("Theorem: "):
            theorem = line.removeprefix("Theorem: ")
            break
    return {
        "subgoals": [
            {
                "id": "normalize-target",
                "theorem": theorem or "theorem normalize_target : True",
                "depends_on": [],
                "context": "Expose definitions and reduce the target to reviewed local obligations.",
            }
        ],
        "rationale": "single reviewed demo decomposition",
    }


def main() -> int:
    request = json.load(sys.stdin)
    agent = request.get("agent", "")
    prompt = str(request.get("prompt", ""))
    if agent == "critic":
        print(json.dumps({
            "ordered_ids": [],
            "feedback": "demo critic preserves proposer order",
        }))
        return 0
    if agent == "decomposer":
        print(json.dumps(decomposition_for(prompt)))
        return 0
    print(json.dumps({"candidates": [candidate_for(prompt)]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
