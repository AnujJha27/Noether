from __future__ import annotations

from typing import Any

from ..manifest import ArchitectureManifest
from .policy import Policy


def assess_manifest(manifest: ArchitectureManifest, policy: Policy) -> dict[str, Any]:
    """Classify evidence without confusing an assertion with a Lean proof."""
    manifest.validate(policy)
    facts = manifest.value["facts"]
    outcomes = []
    for obligation in policy.obligations:
        fact = facts.get(obligation.fact)
        if fact is None:
            status = "inconclusive"
            reason = "required architecture fact is missing"
            evidence_kind = None
        else:
            value = fact["value"]
            satisfied = value if isinstance(value, bool) else (
                value.get("satisfied") if isinstance(value, dict) else None
            )
        if fact is not None and satisfied is False:
            status = "refuted"
            reason = "submitted architecture fact contradicts the obligation"
            evidence_kind = fact["evidence"]["kind"]
        elif fact is not None and satisfied is not True:
            status = "inconclusive"
            reason = "architecture fact does not contain a definite satisfied verdict"
            evidence_kind = fact["evidence"]["kind"]
        elif fact is not None and fact["evidence"]["kind"] == "formal_derivation" and fact["evidence"].get(
            "certificate_declaration"
        ):
            status = "proof_pending_verification"
            reason = "formal evidence was supplied but Lean must verify its declaration"
            evidence_kind = "formal_derivation"
        elif fact is not None:
            status = "proof_required"
            reason = "accepted descriptive evidence is not itself a Lean proof"
            evidence_kind = fact["evidence"]["kind"]
        outcomes.append({
            "id": obligation.id,
            "fact": obligation.fact,
            "required": obligation.required,
            "status": status,
            "reason": reason,
            "evidence_kind": evidence_kind,
        })
    approved = all(item["status"] == "proved" for item in outcomes if item["required"])
    return {
        "policy": {"id": policy.id, "version": policy.version},
        "manifest_sha256": manifest.value["manifest_sha256"],
        "status": "approved" if approved else "not_approved",
        "obligations": outcomes,
    }
