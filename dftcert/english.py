from __future__ import annotations

from typing import Any

from orchestrator.providers import LlmProvider, ProviderError

from .manifest import ArchitectureManifest, ManifestError
from .policy import Policy


def interpretation_schema(policy: Policy) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["facts", "ambiguities", "missing_facts"],
        "properties": {
            "facts": {
                "type": "object",
                "properties": {
                    obligation.fact: {
                        "description": obligation.description,
                    }
                    for obligation in policy.obligations
                },
                "additionalProperties": False,
            },
            "ambiguities": {"type": "array", "items": {"type": "string"}},
            "missing_facts": {"type": "array", "items": {"type": "string"}},
        },
    }


def interpret_english(*, provider: LlmProvider, policy: Policy, model_id: str,
                      description: str) -> ArchitectureManifest:
    obligations = "\n".join(
        f"- {item.fact}: {item.description}" for item in policy.obligations
    )
    response = provider.complete(
        agent="architecture_interpreter",
        system=(
            "Translate an ML architecture description into a draft formal manifest. "
            "Never invent missing properties. Report ambiguity explicitly. Your output "
            "is untrusted until the user confirms it."
        ),
        prompt=(
            f"Policy {policy.id}@{policy.version} requires:\n{obligations}\n\n"
            f"User description:\n{description}\n\n"
            "Return only JSON matching the schema. Include a fact only when the "
            "description actually states it; otherwise list it in missing_facts."
        ),
        schema=interpretation_schema(policy),
    )
    facts = response.get("facts")
    ambiguities = response.get("ambiguities")
    missing = response.get("missing_facts")
    if not isinstance(facts, dict) or not isinstance(ambiguities, list) or not isinstance(missing, list):
        raise ManifestError("English interpreter returned an invalid response shape")
    allowed = set(policy.required_facts)
    if set(facts) - allowed or any(not isinstance(item, str) for item in ambiguities + missing):
        raise ManifestError("English interpreter returned unknown facts or invalid messages")
    manifest = ArchitectureManifest.english_draft(
        model_id=model_id, description=description, policy=policy,
        proposed_facts=facts,
    )
    manifest.value["interpretation"] = {
        "ambiguities": ambiguities,
        "reported_missing_facts": missing,
        "authoritative": False,
    }
    manifest.refresh_hash()
    return manifest
