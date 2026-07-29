from __future__ import annotations

import hashlib
from typing import Any

from .manifest import ArchitectureManifest
from .policy import Policy, PolicyError


def generate_obligations(manifest: ArchitectureManifest, policy: Policy) -> dict[str, Any]:
    """Instantiate trusted policy templates; never synthesize Lean from uploader text."""
    manifest.validate(policy, require_confirmed=True)
    manifest_hash = manifest.value["manifest_sha256"]
    architecture_ir = manifest.value.get("architecture_ir")
    if not isinstance(architecture_ir, dict):
        return {
            "status": "formalization_required",
            "manifest_sha256": manifest_hash,
            "reason": (
                "the manifest has no validated architecture_ir; descriptive facts "
                "cannot be translated into Lean declarations automatically"
            ),
            "obligations": [],
        }
    matching = [
        profile for profile in policy.generation_profiles
        if profile.ir_match == architecture_ir
    ]
    if len(matching) != 1:
        return {
            "status": "formalization_required",
            "manifest_sha256": manifest_hash,
            "reason": "no unique reviewed policy profile matches this architecture_ir",
            "obligations": [],
        }
    profile = matching[0]
    selected = manifest.value.get("formalization", {}).get("profile")
    if selected is not None and selected != profile.id:
        raise PolicyError("manifest formalization profile contradicts architecture_ir")
    try:
        template = profile.preamble_template.read_text(encoding="utf-8")
    except OSError as error:
        raise PolicyError(f"cannot read generation template: {error}") from error
    preamble = template.replace("{{manifest_sha256}}", manifest_hash)
    if "{{" in preamble or "}}" in preamble:
        raise PolicyError("generation template contains an unresolved placeholder")
    preamble_hash = hashlib.sha256(preamble.encode("utf-8")).hexdigest()
    tasks = []
    for obligation in policy.obligations:
        fact = manifest.value["facts"].get(obligation.fact)
        verdict = fact.get("value", {}).get("satisfied") if isinstance(fact, dict) else None
        if verdict is not True:
            task_status = "refuted" if verdict is False else "inconclusive"
        else:
            task_status = "proof_required"
        tasks.append({
            "id": f"{manifest_hash[:12]}-{obligation.id}",
            "obligation_id": obligation.id,
            "fact": obligation.fact,
            "status": task_status,
            "project": policy.project_id,
            "module": profile.module,
            "verification_mode": "generated_obligation",
            "theorem": profile.declarations[obligation.fact],
            "preamble": preamble,
            "preamble_sha256": preamble_hash,
            "manifest_sha256": manifest_hash,
            "limits": profile.proof_limits,
        })
    return {
        "status": "obligations_generated",
        "profile": profile.id,
        "manifest_sha256": manifest_hash,
        "obligations": tasks,
    }
