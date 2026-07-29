from __future__ import annotations

from typing import Any

from .manifest import ArchitectureManifest, ManifestError
from .policy import Policy
from .security import verify_attestation


def apply_extraction_result(*, manifest: ArchitectureManifest, policy: Policy,
                            result: dict[str, Any],
                            trusted_sandbox_result: bool = False,
                            attestation_key: bytes | None = None) -> None:
    """Attach output produced by a separate sandboxed PT2 graph extractor."""
    attestation = result.get("sandbox_attestation")
    signed = (
        isinstance(attestation, dict)
        and attestation_key is not None
        and verify_attestation(attestation, attestation_key)
    )
    if not trusted_sandbox_result and not signed:
        raise ManifestError(
            "extraction result is untrusted; only the sandbox controller may attach it"
        )
    manifest.validate(policy)
    if manifest.value.get("status") != "extraction_pending":
        raise ManifestError("extraction results require a pending PT2 manifest")
    if manifest.value.get("source", {}).get("kind") != "torch_export":
        raise ManifestError("extraction results can only be attached to torch_export input")
    extractor_version = result.get("extractor_version")
    facts = result.get("facts")
    if not isinstance(extractor_version, str) or not extractor_version or not isinstance(facts, dict):
        raise ManifestError("extractor result needs extractor_version and facts")
    allowed = set(policy.required_facts)
    unknown = set(facts) - allowed
    if unknown:
        raise ManifestError(f"extractor returned unknown facts: {', '.join(sorted(unknown))}")
    artifact_hash = manifest.value["source"]["artifact_sha256"]
    if signed and (
        attestation.get("artifact_sha256") != artifact_hash
        or attestation.get("network") != "unshared"
        or attestation.get("filesystem") != "read_only"
    ):
        raise ManifestError("signed sandbox attestation has unsafe or mismatched claims")
    normalized: dict[str, Any] = {}
    for name, raw in facts.items():
        if not isinstance(raw, dict) or "value" not in raw:
            raise ManifestError(f"extracted fact {name!r} is malformed")
        nodes = raw.get("nodes", [])
        if not isinstance(nodes, list) or any(not isinstance(node, str) for node in nodes):
            raise ManifestError(f"extracted fact {name!r} has invalid node provenance")
        normalized[name] = {
            "value": raw["value"],
            "evidence": {
                "kind": "graph_analysis",
                "artifact_sha256": artifact_hash,
                "extractor_version": extractor_version,
                "nodes": nodes,
            },
        }
    missing = [name for name in policy.required_facts if name not in normalized]
    manifest.value["facts"] = normalized
    manifest.value["unresolved_facts"] = missing
    manifest.value["status"] = "extracted_partial" if missing else "extracted"
    manifest.value["extraction"] = {
        "extractor_version": extractor_version,
        "sandbox_attestation": result.get("sandbox_attestation"),
    }
    if "architecture_ir" in result:
        manifest.value["architecture_ir"] = result["architecture_ir"]
    manifest.refresh_hash()
    manifest.validate(policy, require_confirmed=True)
