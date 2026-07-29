from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class SearchTask:
    id: str
    target: str
    theorem: str
    module: str
    project: str
    verification_mode: str = "existing_target"
    preamble: str = ""
    context: str = ""
    parent_attempt_id: str | None = None
    limits: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "SearchTask":
        if not isinstance(value, dict):
            raise ValueError("task must be a JSON object")
        required = ("id", "theorem", "module", "project")
        for name in required:
            if not isinstance(value.get(name), str) or not value[name].strip():
                raise ValueError(f"{name} must be a non-empty string")
        mode = value.get("verification_mode", "existing_target")
        if mode not in {"existing_target", "generated_obligation"}:
            raise ValueError("unsupported verification_mode")
        target = value.get("target", "")
        preamble = value.get("preamble", "")
        if mode == "existing_target":
            if not isinstance(target, str) or not target.strip():
                raise ValueError("target must be a non-empty string")
            if preamble:
                raise ValueError("preamble is only allowed for generated obligations")
        else:
            if target:
                raise ValueError("generated obligations must not contain target")
            if not isinstance(preamble, str) or not preamble.strip():
                raise ValueError("generated obligations require a trusted preamble")
        limits = value.get("limits", {})
        if not isinstance(limits, dict) or any(
            not isinstance(number, int) or isinstance(number, bool) or number <= 0
            for number in limits.values()
        ):
            raise ValueError("limits must contain positive integer values")
        parent = value.get("parent_attempt_id")
        if parent is not None and (not isinstance(parent, str) or not parent):
            raise ValueError("parent_attempt_id must be a non-empty string")
        context = value.get("context", "")
        module = value["module"]
        project = value["project"]
        if not isinstance(context, str) or not isinstance(project, str):
            raise ValueError("context and project must be strings")
        return cls(
            id=value["id"], target=target, theorem=value["theorem"],
            module=module, project=project, context=context,
            verification_mode=mode, preamble=preamble,
            parent_attempt_id=parent, limits=limits,
        )


@dataclass(slots=True)
class Candidate:
    id: str
    patch: str
    rationale: str
    agent: str
    round: int
    parent_node_id: str | None = None
    progress_summary: str = ""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Attempt:
    candidate: Candidate
    status: str
    diagnostics: str = ""
    elapsed_ms: int = 0
    cached: bool = False

    def to_json(self) -> dict[str, Any]:
        value = self.candidate.to_json()
        value.update(
            status=self.status,
            diagnostics=self.diagnostics,
            elapsed_ms=self.elapsed_ms,
            cached=self.cached,
        )
        return value


@dataclass(slots=True)
class SearchNode:
    id: str
    parent_id: str | None
    candidate: Candidate
    status: str
    diagnostics: str
    score: float
    depth: int

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "candidate": self.candidate.to_json(),
            "status": self.status,
            "diagnostics": self.diagnostics,
            "score": self.score,
            "depth": self.depth,
        }
