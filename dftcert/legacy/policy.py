from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class PolicyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Obligation:
    id: str
    fact: str
    description: str
    required: bool
    accepted_evidence: tuple[str, ...]
    value_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CertificateRequirement:
    declaration: str
    expected_type: str
    manifest_hash_constant: str
    manifest_hash_declaration: str


@dataclass(frozen=True, slots=True)
class GenerationProfile:
    id: str
    module: str
    preamble_template: Path
    assembly_template: Path
    ir_match: dict[str, Any]
    declarations: dict[str, str]
    proof_limits: dict[str, int]


@dataclass(frozen=True, slots=True)
class Policy:
    schema_version: int
    id: str
    version: str
    manifest_schema_version: int
    project_id: str
    lean_library: str
    toolchain: str
    obligations: tuple[Obligation, ...]
    generation_profiles: tuple[GenerationProfile, ...]
    architecture_ir_schema: dict[str, Any]
    graph_analysis: dict[str, Any]
    certificate: CertificateRequirement
    source_path: Path

    @classmethod
    def load(cls, path: str | Path) -> "Policy":
        source_path = Path(path).resolve()
        try:
            value = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PolicyError(f"cannot read policy: {error}") from error
        if not isinstance(value, dict):
            raise PolicyError("policy must be a JSON object")

        def text(container: dict[str, Any], name: str) -> str:
            result = container.get(name)
            if not isinstance(result, str) or not result.strip():
                raise PolicyError(f"{name} must be a non-empty string")
            return result

        if value.get("policy_schema_version") != 1:
            raise PolicyError("unsupported policy_schema_version")
        if value.get("manifest_schema_version") != 1:
            raise PolicyError("unsupported manifest_schema_version")
        project = value.get("project")
        certificate = value.get("certificate")
        raw_obligations = value.get("obligations")
        raw_profiles = value.get("generation_profiles", [])
        architecture_ir_schema = value.get("architecture_ir_schema", {})
        graph_analysis = value.get("graph_analysis", {})
        if not isinstance(project, dict) or not isinstance(certificate, dict):
            raise PolicyError("project and certificate must be objects")
        if not isinstance(raw_obligations, list) or not raw_obligations:
            raise PolicyError("obligations must be a non-empty array")
        if not isinstance(raw_profiles, list):
            raise PolicyError("generation_profiles must be an array")
        if not isinstance(architecture_ir_schema, dict) or not isinstance(graph_analysis, dict):
            raise PolicyError("architecture_ir_schema and graph_analysis must be objects")
        obligations: list[Obligation] = []
        seen_ids: set[str] = set()
        seen_facts: set[str] = set()
        for index, raw in enumerate(raw_obligations):
            if not isinstance(raw, dict):
                raise PolicyError(f"obligations[{index}] must be an object")
            obligation_id = text(raw, "id")
            fact = text(raw, "fact")
            if obligation_id in seen_ids or fact in seen_facts:
                raise PolicyError("obligation IDs and fact names must be unique")
            evidence = raw.get("accepted_evidence")
            value_schema = raw.get("value_schema")
            if not isinstance(evidence, list) or not evidence or any(
                not isinstance(item, str) or not item for item in evidence
            ):
                raise PolicyError(f"obligations[{index}].accepted_evidence is invalid")
            required = raw.get("required")
            if not isinstance(required, bool):
                raise PolicyError(f"obligations[{index}].required must be boolean")
            if not isinstance(value_schema, dict):
                raise PolicyError(f"obligations[{index}].value_schema must be an object")
            obligations.append(Obligation(
                id=obligation_id, fact=fact, description=text(raw, "description"),
                required=required, accepted_evidence=tuple(evidence),
                value_schema=value_schema,
            ))
            seen_ids.add(obligation_id)
            seen_facts.add(fact)
        profiles: list[GenerationProfile] = []
        profile_ids: set[str] = set()
        for index, raw in enumerate(raw_profiles):
            if not isinstance(raw, dict):
                raise PolicyError(f"generation_profiles[{index}] must be an object")
            profile_id = text(raw, "id")
            declarations = raw.get("declarations")
            if profile_id in profile_ids:
                raise PolicyError("generation profile IDs must be unique")
            if not isinstance(declarations, dict) or set(declarations) != seen_facts or any(
                not isinstance(item, str) or not item.strip() for item in declarations.values()
            ):
                raise PolicyError(
                    f"generation_profiles[{index}].declarations must cover every policy fact"
                )
            template = (source_path.parent / text(raw, "preamble_template")).resolve()
            assembly = (source_path.parent / text(raw, "assembly_template")).resolve()
            try:
                template.relative_to(source_path.parent)
                assembly.relative_to(source_path.parent)
            except ValueError as error:
                raise PolicyError("generation template escapes the policy directory") from error
            ir_match = raw.get("ir_match")
            if not isinstance(ir_match, dict) or not ir_match:
                raise PolicyError(f"generation_profiles[{index}].ir_match must be an object")
            proof_limits = raw.get("proof_limits", {})
            if not isinstance(proof_limits, dict) or any(
                not isinstance(number, int) or isinstance(number, bool) or number <= 0
                for number in proof_limits.values()
            ):
                raise PolicyError(
                    f"generation_profiles[{index}].proof_limits must be positive integers"
                )
            profiles.append(GenerationProfile(
                id=profile_id,
                module=text(raw, "module"),
                preamble_template=template,
                assembly_template=assembly,
                ir_match=ir_match,
                declarations=dict(declarations),
                proof_limits=dict(proof_limits),
            ))
            profile_ids.add(profile_id)
        return cls(
            schema_version=1,
            id=text(value, "id"), version=text(value, "version"),
            manifest_schema_version=1,
            project_id=text(project, "id"), lean_library=text(project, "lean_library"),
            toolchain=text(project, "toolchain"),
            obligations=tuple(obligations),
            generation_profiles=tuple(profiles),
            architecture_ir_schema=architecture_ir_schema,
            graph_analysis=graph_analysis,
            certificate=CertificateRequirement(
                declaration=text(certificate, "declaration"),
                expected_type=text(certificate, "expected_type"),
                manifest_hash_constant=text(certificate, "manifest_hash_constant"),
                manifest_hash_declaration=text(certificate, "manifest_hash_declaration"),
            ),
            source_path=source_path,
        )

    @property
    def required_facts(self) -> tuple[str, ...]:
        return tuple(item.fact for item in self.obligations if item.required)

    def obligation_for_fact(self, fact: str) -> Obligation:
        for obligation in self.obligations:
            if obligation.fact == fact:
                return obligation
        raise PolicyError(f"policy does not define fact {fact!r}")

    def generation_profile(self, profile_id: str) -> GenerationProfile:
        for profile in self.generation_profiles:
            if profile.id == profile_id:
                return profile
        raise PolicyError(f"policy does not define formalization profile {profile_id!r}")
