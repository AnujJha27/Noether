from __future__ import annotations

from typing import Any

from .assessment import assess_manifest
from .manifest import ArchitectureManifest, sha256_value
from .obligations import generate_obligations
from .policy import Policy


def _proof_by_obligation(proof_results: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for result in proof_results or []:
        if not isinstance(result, dict):
            continue
        task_id = result.get("id")
        if isinstance(task_id, str):
            indexed[task_id] = result
    return indexed


def _category(
    *,
    assessment_status: str,
    generated_status: str | None,
    proof_status: str | None,
) -> str:
    if proof_status == "verified":
        return "consistent_with_policy"
    if assessment_status == "refuted":
        return "violates_required_principle"
    if assessment_status == "inconclusive":
        return "inconclusive_missing_assumption"
    if generated_status == "formalization_required":
        return "formalization_gap"
    if proof_status in {"lean_error", "no_candidate_verified"}:
        return "proof_search_failed"
    if proof_status in {"timeout", "worker_failure", "memory_limit"}:
        return "proof_search_inconclusive"
    return "proof_required"


def sanity_report(
    *,
    manifest: ArchitectureManifest,
    policy: Policy,
    proof_results: list[dict[str, Any]] | None = None,
    certificate_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a physicist-facing report without hiding formalization gaps."""
    manifest.validate(policy)
    assessment = assess_manifest(manifest, policy)
    try:
        generation = generate_obligations(manifest, policy)
    except Exception as error:
        generation = {
            "status": "formalization_required",
            "reason": str(error),
            "obligations": [],
        }
    proof_index = _proof_by_obligation(proof_results)
    task_by_fact = {
        item["fact"]: item for item in generation.get("obligations", [])
        if isinstance(item, dict) and isinstance(item.get("fact"), str)
    }
    items = []
    for obligation in assessment["obligations"]:
        fact = obligation["fact"]
        task = task_by_fact.get(fact)
        proof = proof_index.get(task["id"]) if task else None
        proof_status = proof.get("status") if proof else None
        category = _category(
            assessment_status=obligation["status"],
            generated_status=generation["status"],
            proof_status=proof_status,
        )
        reason = obligation["reason"]
        if proof_status == "verified":
            reason = "Lean verified a proof for the generated obligation"
        trace = [
            item for item in manifest.value.get("traceability", [])
            if item.get("normalized_claim") == fact
        ]
        fact_value = manifest.value.get("facts", {}).get(fact, {})
        items.append({
            "obligation_id": obligation["id"],
            "fact": fact,
            "principle": policy.obligation_for_fact(fact).description,
            "category": category,
            "assessment_status": obligation["status"],
            "reason": reason,
            "evidence_kind": obligation["evidence_kind"],
            "normalized_claim": fact_value.get("value"),
            "lean_task_id": task.get("id") if task else None,
            "lean_theorem": task.get("theorem") if task else None,
            "proof_status": proof_status,
            "diagnostics": proof.get("diagnostics") if proof else None,
            "traceability": trace,
        })
    if certificate_report and certificate_report.get("status") == "approved":
        overall = "consistent_with_policy"
    elif any(item["category"] == "violates_required_principle" for item in items):
        overall = "violates_required_principle"
    elif any(item["category"] == "inconclusive_missing_assumption" for item in items):
        overall = "inconclusive_missing_assumption"
    elif any(item["category"] == "formalization_gap" for item in items):
        overall = "formalization_gap"
    elif items and all(item["category"] == "consistent_with_policy" for item in items):
        overall = "consistent_with_policy"
    else:
        overall = "proof_required"
    report = {
        "report_schema_version": 1,
        "policy": {"id": policy.id, "version": policy.version},
        "manifest_sha256": manifest.value["manifest_sha256"],
        "status": overall,
        "summary": _summary(overall),
        "assumptions": manifest.value.get("assumptions", []),
        "clarification_questions": manifest.value.get("clarification_questions", []),
        "obligations": items,
        "generation": {
            "status": generation["status"],
            "reason": generation.get("reason"),
            "profile": generation.get("profile"),
        },
        "limitations": [
            "This report checks only principles encoded in the selected policy.",
            "User-confirmed descriptions are evidence about the submitted description, not executable model inspection.",
            "Lean proof success does not certify trained weights, numerical accuracy, or experimental validity.",
        ],
    }
    report["report_sha256"] = sha256_value(report)
    return report


def _summary(status: str) -> str:
    messages = {
        "consistent_with_policy": (
            "The checked obligations are consistent with the selected formal policy."
        ),
        "violates_required_principle": (
            "At least one required principle is contradicted by the submitted claim."
        ),
        "formalization_gap": (
            "The claim has descriptive evidence, but no reviewed Lean formalization profile matches it yet."
        ),
        "inconclusive_missing_assumption": (
            "The policy needs additional assumptions before a formal sanity check can proceed."
        ),
        "proof_required": (
            "The claim is structured, but Lean proof search/certificate checking has not completed."
        ),
    }
    return messages.get(status, "The sanity check is inconclusive.")
