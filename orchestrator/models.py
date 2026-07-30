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
    subgoals: list[dict[str, Any]] = field(default_factory=list)

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
        subgoals = value.get("subgoals", [])
        if not isinstance(subgoals, list):
            raise ValueError("subgoals must be an array")
        normalized_subgoals: list[dict[str, Any]] = []
        seen_subgoals: set[str] = set()
        for index, subgoal in enumerate(subgoals):
            if not isinstance(subgoal, dict):
                raise ValueError(f"subgoals[{index}] must be an object")
            subgoal_id = subgoal.get("id")
            statement = subgoal.get("theorem", subgoal.get("statement", ""))
            depends_on = subgoal.get("depends_on", [])
            if not isinstance(subgoal_id, str) or not subgoal_id.strip():
                raise ValueError(f"subgoals[{index}].id must be a non-empty string")
            if subgoal_id in seen_subgoals:
                raise ValueError(f"duplicate subgoal id {subgoal_id!r}")
            if not isinstance(statement, str) or not statement.strip():
                raise ValueError(f"subgoals[{index}] requires theorem or statement")
            if not isinstance(depends_on, list) or any(
                not isinstance(item, str) or not item for item in depends_on
            ):
                raise ValueError(f"subgoals[{index}].depends_on must be an array of strings")
            normalized_subgoals.append({
                "id": subgoal_id,
                "theorem": statement,
                "depends_on": list(depends_on),
                "context": subgoal.get("context", "") if isinstance(subgoal.get("context", ""), str) else "",
            })
            seen_subgoals.add(subgoal_id)
        for subgoal in normalized_subgoals:
            missing = set(subgoal["depends_on"]) - seen_subgoals
            if missing:
                raise ValueError(
                    f"subgoal {subgoal['id']!r} depends on unknown subgoals: "
                    + ", ".join(sorted(missing))
                )
        module = value["module"]
        project = value["project"]
        if not isinstance(context, str) or not isinstance(project, str):
            raise ValueError("context and project must be strings")
        return cls(
            id=value["id"], target=target, theorem=value["theorem"],
            module=module, project=project, context=context,
            verification_mode=mode, preamble=preamble,
            parent_attempt_id=parent, limits=limits,
            subgoals=normalized_subgoals,
        )

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


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


@dataclass(slots=True)
class Handoff:
    id: str
    round: int
    from_agent: str
    to_agent: str
    node_id: str
    reason: str
    state_summary: str
    accepted: bool = False

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class HandoffReceipt:
    handoff_id: str
    round: int
    receiver_agent: str
    accepted: bool
    receiver_summary: str
    plan: str
    risks: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AgentTurn:
    id: str
    round: int
    agent: str
    role: str
    action: str
    status: str
    parent_node_id: str | None = None
    received_handoff_id: str | None = None
    input_summary: str = ""
    output_summary: str = ""
    candidate_ids: list[str] = field(default_factory=list)
    error: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SupervisorDecision:
    id: str
    round: int
    action: str
    reason: str
    assignments: dict[str, str | None] = field(default_factory=dict)
    budget_state: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)
