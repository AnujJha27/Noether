from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .policy import Policy


class ManifestError(ValueError):
    pass


def validate_value_schema(value: Any, schema: dict[str, Any], path: str) -> None:
    expected = schema.get("type")
    checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "boolean": lambda item: isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
    }
    if expected not in checks or not checks[expected](value):
        raise ManifestError(f"{path} must have schema type {expected}")
    if "enum" in schema and value not in schema["enum"]:
        raise ManifestError(f"{path} is not an allowed value")
    if expected == "object":
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        missing = set(required) - set(value)
        if missing:
            raise ManifestError(f"{path} is missing: {', '.join(sorted(missing))}")
        if schema.get("additionalProperties") is False:
            unknown = set(value) - set(properties)
            if unknown:
                raise ManifestError(f"{path} has unknown fields: {', '.join(sorted(unknown))}")
        for name, child in value.items():
            if name in properties:
                validate_value_schema(child, properties[name], f"{path}.{name}")
    if expected == "array":
        if len(value) < schema.get("minItems", 0):
            raise ManifestError(f"{path} has too few items")
        if isinstance(schema.get("items"), dict):
            for index, child in enumerate(value):
                validate_value_schema(child, schema["items"], f"{path}[{index}]")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(slots=True)
class ArchitectureManifest:
    value: dict[str, Any]

    @classmethod
    def english_draft(cls, *, model_id: str, description: str, policy: Policy,
                      proposed_facts: dict[str, Any] | None = None) -> "ArchitectureManifest":
        if not model_id.strip() or not description.strip():
            raise ManifestError("model_id and description must be non-empty")
        proposed_facts = proposed_facts or {}
        unknown = set(proposed_facts) - set(policy.required_facts)
        if unknown:
            raise ManifestError(f"unknown policy facts: {', '.join(sorted(unknown))}")
        facts = {
            name: {
                "value": value,
                "evidence": {
                    "kind": "unconfirmed_interpretation",
                    "description_sha256": hashlib.sha256(description.encode()).hexdigest(),
                },
            }
            for name, value in proposed_facts.items()
        }
        manifest = cls({
            "manifest_schema_version": 1,
            "model_id": model_id,
            "policy": {"id": policy.id, "version": policy.version},
            "status": "draft",
            "source": {
                "kind": "english",
                "description": description,
                "description_sha256": hashlib.sha256(description.encode()).hexdigest(),
            },
            "input_constraints": {},
            "facts": facts,
            "unresolved_facts": [name for name in policy.required_facts if name not in facts],
        })
        manifest.refresh_hash()
        return manifest

    @classmethod
    def load(cls, path: str | Path) -> "ArchitectureManifest":
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ManifestError(f"cannot read manifest: {error}") from error
        if not isinstance(value, dict):
            raise ManifestError("manifest must be a JSON object")
        return cls(value)

    def payload(self) -> dict[str, Any]:
        result = copy.deepcopy(self.value)
        result.pop("manifest_sha256", None)
        return result

    def refresh_hash(self) -> str:
        digest = sha256_value(self.payload())
        self.value["manifest_sha256"] = digest
        return digest

    def validate(self, policy: Policy, *, require_confirmed: bool = False) -> None:
        value = self.value
        if value.get("manifest_schema_version") != policy.manifest_schema_version:
            raise ManifestError("manifest schema does not match policy")
        if value.get("policy") != {"id": policy.id, "version": policy.version}:
            raise ManifestError("manifest policy identity does not match")
        expected_hash = value.get("manifest_sha256")
        if not isinstance(expected_hash, str) or expected_hash != sha256_value(self.payload()):
            raise ManifestError("manifest hash is missing or invalid")
        status = value.get("status")
        if status not in {
            "draft", "confirmed", "extraction_pending", "extracted_partial", "extracted"
        }:
            raise ManifestError("invalid manifest status")
        if require_confirmed and status not in {"confirmed", "extracted_partial", "extracted"}:
            raise ManifestError("manifest requires explicit confirmation or extraction")
        facts = value.get("facts")
        if not isinstance(facts, dict):
            raise ManifestError("facts must be an object")
        unknown = set(facts) - set(item.fact for item in policy.obligations)
        if unknown:
            raise ManifestError(f"manifest contains unknown facts: {', '.join(sorted(unknown))}")
        for name, fact in facts.items():
            if not isinstance(fact, dict) or "value" not in fact or not isinstance(fact.get("evidence"), dict):
                raise ManifestError(f"fact {name!r} is malformed")
            kind = fact["evidence"].get("kind")
            obligation = policy.obligation_for_fact(name)
            validate_value_schema(fact["value"], obligation.value_schema, f"facts.{name}.value")
            if status in {"confirmed", "extracted_partial", "extracted"} and kind not in obligation.accepted_evidence:
                raise ManifestError(f"fact {name!r} has unacceptable evidence kind {kind!r}")
        architecture_ir = value.get("architecture_ir")
        if architecture_ir is not None:
            if not policy.architecture_ir_schema:
                raise ManifestError("policy does not accept architecture_ir")
            validate_value_schema(
                architecture_ir, policy.architecture_ir_schema, "architecture_ir"
            )
        if status in {"confirmed", "extracted"}:
            missing = set(policy.required_facts) - set(facts)
            if missing:
                raise ManifestError(f"required facts are missing: {', '.join(sorted(missing))}")

    def confirm_english(self, policy: Policy, confirmed_facts: dict[str, Any]) -> None:
        self.validate(policy)
        if self.value.get("status") != "draft" or self.value.get("source", {}).get("kind") != "english":
            raise ManifestError("only an English draft can be confirmed")
        missing = set(policy.required_facts) - set(confirmed_facts)
        extra = set(confirmed_facts) - set(policy.required_facts)
        if missing or extra:
            details = []
            if missing:
                details.append("missing " + ", ".join(sorted(missing)))
            if extra:
                details.append("unknown " + ", ".join(sorted(extra)))
            raise ManifestError("confirmation facts do not match policy: " + "; ".join(details))
        description_hash = self.value["source"]["description_sha256"]
        self.value["facts"] = {
            name: {
                "value": confirmed_facts[name],
                "evidence": {
                    "kind": "user_attestation",
                    "description_sha256": description_hash,
                },
            }
            for name in policy.required_facts
        }
        self.value["status"] = "confirmed"
        self.value["confirmed_at"] = datetime.now(timezone.utc).isoformat()
        self.value["unresolved_facts"] = []
        self.refresh_hash()
        self.validate(policy, require_confirmed=True)

    def attach_architecture_ir(self, policy: Policy, architecture_ir: dict[str, Any]) -> None:
        if self.value.get("status") not in {"draft", "confirmed"}:
            raise ManifestError("architecture IR can only be attached during English review")
        validate_value_schema(
            architecture_ir, policy.architecture_ir_schema, "architecture_ir"
        )
        self.value["architecture_ir"] = copy.deepcopy(architecture_ir)
        self.refresh_hash()
        self.validate(policy)

    def write(self, path: str | Path) -> None:
        self.refresh_hash()
        Path(path).write_text(json.dumps(self.value, indent=2, sort_keys=True,
                                         ensure_ascii=False) + "\n", encoding="utf-8")
