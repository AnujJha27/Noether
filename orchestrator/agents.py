from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class AgentRegistryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AgentSpec:
    name: str
    kind: str
    instructions: str
    model: str = "default"
    tools: tuple[str, ...] = field(default_factory=tuple)
    max_candidates: int | None = None
    handoff_targets: tuple[str, ...] = field(default_factory=tuple)
    temperature: float | None = None
    explicit_tools: bool = False

    @classmethod
    def from_json(cls, name: str, value: Any) -> "AgentSpec":
        if isinstance(value, str):
            return cls(name=name, kind="proposer", instructions=value)
        if not isinstance(value, dict):
            raise AgentRegistryError(f"agent {name!r} must be a string or object")
        kind = value.get("kind", "proposer")
        instructions = value.get("instructions", value.get("prompt", ""))
        model = value.get("model", "default")
        tools = value.get("tools", [])
        handoff_targets = value.get("handoff_targets", [])
        max_candidates = value.get("max_candidates")
        temperature = value.get("temperature")
        explicit_tools = value.get("explicit_tools", True)
        if kind not in {"proposer", "critic", "decomposer", "supervisor", "reporter"}:
            raise AgentRegistryError(f"agent {name!r} has unsupported kind {kind!r}")
        if not isinstance(instructions, str) or not instructions.strip():
            raise AgentRegistryError(f"agent {name!r} requires non-empty instructions")
        if not isinstance(model, str) or not model:
            raise AgentRegistryError(f"agent {name!r} model must be a non-empty string")
        if not isinstance(tools, list) or any(not isinstance(item, str) or not item for item in tools):
            raise AgentRegistryError(f"agent {name!r} tools must be strings")
        if not isinstance(handoff_targets, list) or any(
            not isinstance(item, str) or not item for item in handoff_targets
        ):
            raise AgentRegistryError(f"agent {name!r} handoff_targets must be strings")
        if max_candidates is not None and (
            not isinstance(max_candidates, int)
            or isinstance(max_candidates, bool)
            or max_candidates <= 0
        ):
            raise AgentRegistryError(f"agent {name!r} max_candidates must be positive")
        if temperature is not None and (
            not isinstance(temperature, (int, float)) or isinstance(temperature, bool)
        ):
            raise AgentRegistryError(f"agent {name!r} temperature must be numeric")
        if not isinstance(explicit_tools, bool):
            raise AgentRegistryError(f"agent {name!r} explicit_tools must be boolean")
        return cls(
            name=name,
            kind=kind,
            instructions=instructions,
            model=model,
            tools=tuple(tools),
            max_candidates=max_candidates,
            handoff_targets=tuple(handoff_targets),
            temperature=float(temperature) if temperature is not None else None,
            explicit_tools=explicit_tools,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "instructions": self.instructions,
            "model": self.model,
            "tools": list(self.tools),
            "max_candidates": self.max_candidates,
            "handoff_targets": list(self.handoff_targets),
            "temperature": self.temperature,
            "explicit_tools": self.explicit_tools,
        }


@dataclass(frozen=True, slots=True)
class AgentRegistry:
    agents: dict[str, AgentSpec]

    @classmethod
    def load(cls, path: str | Path) -> "AgentRegistry":
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not value:
            raise AgentRegistryError("agent registry must be a non-empty object")
        agents = {
            name: AgentSpec.from_json(name, spec)
            for name, spec in value.items()
            if isinstance(name, str) and name
        }
        if len(agents) != len(value):
            raise AgentRegistryError("agent names must be non-empty strings")
        for spec in agents.values():
            unknown = set(spec.handoff_targets) - set(agents)
            if unknown:
                raise AgentRegistryError(
                    f"agent {spec.name!r} has unknown handoff targets: "
                    + ", ".join(sorted(unknown))
                )
        return cls(agents)

    @classmethod
    def from_roles(cls, roles: dict[str, str]) -> "AgentRegistry":
        return cls({
            name: AgentSpec(name=name, kind="proposer", instructions=instructions)
            for name, instructions in roles.items()
        })

    def proposer_specs(self) -> dict[str, AgentSpec]:
        return {
            name: spec for name, spec in self.agents.items()
            if spec.kind == "proposer"
        }

    def critic_spec(self) -> AgentSpec | None:
        for spec in self.agents.values():
            if spec.kind == "critic":
                return spec
        return None

    def decomposer_spec(self) -> AgentSpec | None:
        for spec in self.agents.values():
            if spec.kind == "decomposer":
                return spec
        return None

    def to_json(self) -> dict[str, Any]:
        return {name: spec.to_json() for name, spec in self.agents.items()}


def load_agent_registry(path: str | Path) -> AgentRegistry:
    return AgentRegistry.load(path)
