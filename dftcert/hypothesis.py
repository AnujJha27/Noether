from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .manifest import ArchitectureManifest
from .policy import Policy


@dataclass(frozen=True, slots=True)
class ExtractedClaim:
    fact: str
    value: dict[str, Any]
    original_text: str
    confidence: str
    rationale: str


def _sentence_containing(text: str, patterns: tuple[str, ...]) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    lowered_patterns = tuple(pattern.lower() for pattern in patterns)
    for sentence in sentences:
        lowered = sentence.lower()
        if any(pattern in lowered for pattern in lowered_patterns):
            return sentence.strip()
    return text.strip()


def _mentions(text: str, *patterns: str) -> bool:
    lowered = text.lower()
    return any(pattern in lowered for pattern in patterns)


def extract_claims(hypothesis: str, policy: Policy) -> tuple[list[ExtractedClaim], list[dict[str, Any]]]:
    """Conservative deterministic extraction for physicist-facing drafts.

    The extractor intentionally produces reviewable draft claims. It never marks
    claims authoritative; confirmation or graph analysis must do that later.
    """
    if not hypothesis.strip():
        raise ValueError("hypothesis must be non-empty")
    claims: list[ExtractedClaim] = []
    ambiguities: list[dict[str, Any]] = []

    if "xc_discontinuity_compatible" in policy.required_facts:
        if _mentions(hypothesis, "derivative discontinuity", "xc discontinuity"):
            claims.append(ExtractedClaim(
                fact="xc_discontinuity_compatible",
                value={
                    "satisfied": True,
                    "mechanism": "user-described derivative discontinuity",
                    "electron_boundaries": [0],
                },
                original_text=_sentence_containing(
                    hypothesis, ("derivative discontinuity", "xc discontinuity")
                ),
                confidence="medium",
                rationale=(
                    "The hypothesis explicitly mentions an XC/derivative "
                    "discontinuity, but the electron boundary remains a default "
                    "draft value until confirmed."
                ),
            ))
        elif _mentions(hypothesis, "smooth xc", "continuous derivative", "no discontinuity"):
            claims.append(ExtractedClaim(
                fact="xc_discontinuity_compatible",
                value={
                    "satisfied": False,
                    "mechanism": "user-described smooth/continuous XC response",
                    "electron_boundaries": [],
                },
                original_text=_sentence_containing(
                    hypothesis, ("smooth xc", "continuous derivative", "no discontinuity")
                ),
                confidence="medium",
                rationale="The hypothesis appears to rule out an XC discontinuity.",
            ))

    if "spatial_nonlocality_compatible" in policy.required_facts:
        if _mentions(hypothesis, "nonlocal", "long-range", "message passing", "global coupling"):
            claims.append(ExtractedClaim(
                fact="spatial_nonlocality_compatible",
                value={
                    "satisfied": True,
                    "receptive_field": 1,
                    "required_couplings": [],
                    "uncovered_couplings": [],
                },
                original_text=_sentence_containing(
                    hypothesis, ("nonlocal", "long-range", "message passing", "global coupling")
                ),
                confidence="medium",
                rationale=(
                    "The hypothesis describes nonlocal/coupled behavior; the "
                    "exact receptive field should be confirmed by the user or "
                    "graph analysis."
                ),
            ))
        elif _mentions(hypothesis, "strictly local", "pointwise", "local only"):
            claims.append(ExtractedClaim(
                fact="spatial_nonlocality_compatible",
                value={
                    "satisfied": False,
                    "receptive_field": 0,
                    "required_couplings": [{"kind": "unspecified_nonlocal_coupling"}],
                    "uncovered_couplings": [{"kind": "unspecified_nonlocal_coupling"}],
                },
                original_text=_sentence_containing(
                    hypothesis, ("strictly local", "pointwise", "local only")
                ),
                confidence="medium",
                rationale="The hypothesis appears to restrict the architecture to local interactions.",
            ))

    if "self_adjoint" in policy.required_facts:
        if _mentions(
            hypothesis,
            "does not specify self-adjoint",
            "does not specify self adjoint",
            "unspecified self-adjoint",
            "unspecified self adjoint",
            "no statement about self-adjoint",
            "no statement about self adjoint",
        ):
            pass
        elif _mentions(hypothesis, "non-self-adjoint", "not self-adjoint", "not hermitian"):
            claims.append(ExtractedClaim(
                fact="self_adjoint",
                value={
                    "satisfied": False,
                    "enforcement": "hypothesis states the operator is not self-adjoint",
                },
                original_text=_sentence_containing(
                    hypothesis, ("non-self-adjoint", "not self-adjoint", "not hermitian")
                ),
                confidence="high",
                rationale="The hypothesis explicitly negates self-adjointness.",
            ))
        elif _mentions(hypothesis, "self-adjoint", "self adjoint", "hermitian", "symmetric operator"):
            claims.append(ExtractedClaim(
                fact="self_adjoint",
                value={
                    "satisfied": True,
                    "enforcement": "user-described symmetric/self-adjoint construction",
                },
                original_text=_sentence_containing(
                    hypothesis, ("self-adjoint", "self adjoint", "hermitian", "symmetric operator")
                ),
                confidence="medium",
                rationale=(
                    "The hypothesis asserts self-adjointness; confirmation or "
                    "formal derivation is still required."
                ),
            ))

    extracted = {claim.fact for claim in claims}
    for obligation in policy.obligations:
        if obligation.required and obligation.fact not in extracted:
            ambiguities.append({
                "fact": obligation.fact,
                "obligation_id": obligation.id,
                "question": _question_for_fact(obligation.fact),
                "reason": "The hypothesis did not provide enough information for this required principle.",
            })
    return claims, ambiguities


def _question_for_fact(fact: str) -> str:
    questions = {
        "xc_discontinuity_compatible": (
            "Does the architecture intentionally support a nonzero XC derivative "
            "discontinuity, and at which electron-number boundary?"
        ),
        "spatial_nonlocality_compatible": (
            "What receptive field or coupling structure should cover the required "
            "spatial/nonlocal interactions?"
        ),
        "self_adjoint": (
            "Is the learned self-energy/operator self-adjoint? If yes, what "
            "construction enforces that property?"
        ),
    }
    return questions.get(fact, f"What assumption should be used for {fact}?")


def _formalization_question(policy: Policy) -> dict[str, Any] | None:
    if not policy.generation_profiles:
        return None
    return {
        "fact": "architecture_ir",
        "question": (
            "Which reviewed architecture formalization profile matches this "
            "hypothesis, if any?"
        ),
        "known_profiles": [profile.id for profile in policy.generation_profiles],
        "reason": (
            "Descriptive physics claims are not automatically converted into Lean "
            "models without a reviewed architecture_ir/profile."
        ),
    }


def draft_hypothesis(*, model_id: str, hypothesis: str, policy: Policy) -> ArchitectureManifest:
    claims, ambiguities = extract_claims(hypothesis, policy)
    proposed = {claim.fact: claim.value for claim in claims}
    manifest = ArchitectureManifest.english_draft(
        model_id=model_id, description=hypothesis, policy=policy,
        proposed_facts=proposed,
    )
    source_hash = manifest.value["source"]["description_sha256"]
    for claim in claims:
        manifest.value["facts"][claim.fact]["evidence"] = {
            "kind": "unconfirmed_interpretation",
            "description_sha256": source_hash,
            "confidence": claim.confidence,
            "rationale": claim.rationale,
        }
    assumptions = []
    traceability = []
    for claim in claims:
        assumptions.append({
            "id": claim.fact,
            "statement": policy.obligation_for_fact(claim.fact).description,
            "value": claim.value,
            "source": "llm_or_heuristic_interpretation",
            "status": "needs_user_confirmation",
            "confidence": claim.confidence,
        })
        traceability.append({
            "original_text": claim.original_text,
            "normalized_claim": claim.fact,
            "draft_value": claim.value,
            "evidence_kind": "unconfirmed_interpretation",
            "confirmation_required": True,
        })
    for item in ambiguities:
        assumptions.append({
            "id": item["fact"],
            "statement": policy.obligation_for_fact(item["fact"]).description,
            "source": "missing",
            "status": "needs_clarification",
        })
    questions = list(ambiguities)
    formalization = _formalization_question(policy)
    if formalization:
        questions.append(formalization)
    manifest.value["hypothesis_intake"] = {
        "status": "draft_requires_review",
        "extractor": "deterministic-keyword-v1",
        "extracted_claim_count": len(claims),
        "ambiguous_or_missing_count": len(ambiguities),
    }
    manifest.value["assumptions"] = assumptions
    manifest.value["clarification_questions"] = questions
    manifest.value["traceability"] = traceability
    manifest.refresh_hash()
    return manifest


def policy_coverage(policy: Policy) -> dict[str, Any]:
    return {
        "policy": {"id": policy.id, "version": policy.version},
        "project": {
            "id": policy.project_id,
            "lean_library": policy.lean_library,
            "toolchain": policy.toolchain,
        },
        "supported_claims": [
            {
                "obligation_id": obligation.id,
                "fact": obligation.fact,
                "description": obligation.description,
                "required": obligation.required,
                "accepted_evidence": list(obligation.accepted_evidence),
                "value_schema": obligation.value_schema,
            }
            for obligation in policy.obligations
        ],
        "formalization_profiles": [
            {
                "id": profile.id,
                "module": profile.module,
                "ir_match": profile.ir_match,
                "facts": sorted(profile.declarations),
            }
            for profile in policy.generation_profiles
        ],
        "not_supported": [
            "trained-weight certification",
            "numerical accuracy or convergence guarantees",
            "agreement with experiment",
            "arbitrary Python model execution",
            "public multi-tenant uploads without container/cgroup hardening",
            "physics domains not represented by the selected policy",
        ],
    }
