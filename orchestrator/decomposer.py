from __future__ import annotations

from typing import Any

from .agents import AgentSpec
from .models import SearchTask
from .permissions import PermissionPolicy


DECOMPOSITION_SCHEMA = {
    "type": "object",
    "required": ["subgoals"],
    "properties": {
        "subgoals": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "theorem"],
                "properties": {
                    "id": {"type": "string"},
                    "theorem": {"type": "string"},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "context": {"type": "string"},
                },
            },
        },
        "rationale": {"type": "string"},
    },
}


def decompose_task(
    *,
    task: SearchTask,
    agent: AgentSpec,
    complete,
    permissions: PermissionPolicy,
) -> dict[str, Any]:
    permissions.require(agent, "task_decompose")
    prompt = (
        "Decompose this Lean proof-search task into useful subgoals. "
        "Return only a JSON object matching the schema. Subgoal IDs must be stable.\n\n"
        f"Task id: {task.id}\n"
        f"Target: {task.target}\n"
        f"Theorem: {task.theorem}\n"
        f"Context:\n{task.context or '(none)'}\n"
        f"Existing subgoals:\n{task.subgoals}\n"
    )
    return complete(
        agent,
        system=agent.instructions,
        prompt=prompt,
        schema=DECOMPOSITION_SCHEMA,
    )
