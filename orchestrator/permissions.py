from __future__ import annotations

from dataclasses import dataclass

from .agents import AgentSpec


class PermissionError(RuntimeError):
    pass


DEFAULT_KIND_TOOLS = {
    "proposer": {"lean_diagnostics", "frontier_read", "candidate_submit"},
    "critic": {"candidate_rank", "frontier_read"},
    "decomposer": {"task_decompose", "policy_read"},
    "supervisor": {"schedule", "handoff", "budget_read"},
    "reporter": {"trace_read", "report_write"},
}


@dataclass(frozen=True, slots=True)
class PermissionPolicy:
    def allowed_tools(self, agent: AgentSpec) -> set[str]:
        if agent.explicit_tools:
            return set(agent.tools)
        return set(DEFAULT_KIND_TOOLS.get(agent.kind, set())) | set(agent.tools)

    def require(self, agent: AgentSpec, tool: str) -> None:
        if tool not in self.allowed_tools(agent):
            raise PermissionError(
                f"agent {agent.name!r} of kind {agent.kind!r} cannot use tool {tool!r}"
            )
