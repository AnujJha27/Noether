from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .models import AgentTurn, Attempt, Handoff, SearchNode, SupervisorDecision


@dataclass(frozen=True, slots=True)
class AgentAssignment:
    role: str
    parent: SearchNode | None
    handoff: Handoff | None


class SupervisorPolicy:
    """Deterministic supervisor for proof-search agents.

    This keeps the framework auditable: the model proposes Lean patches, but the
    local supervisor owns budgets, frontier assignment, and handoff accounting.
    """

    def __init__(self, roles: list[str]):
        if not roles:
            raise ValueError("supervisor requires at least one role")
        self.roles = roles

    def decide(
        self,
        *,
        round_number: int,
        model_calls: int,
        max_model_calls: int,
        seen_candidates: int,
        max_candidates: int,
        winner_present: bool,
        frontier: list[SearchNode],
        subgoal_count: int = 0,
    ) -> SupervisorDecision:
        if winner_present:
            return SupervisorDecision(
                id=f"supervisor-r{round_number}",
                round=round_number,
                action="stop",
                reason="a verified winner already exists",
                assignments={},
                budget_state={
                    "model_calls": model_calls,
                    "max_model_calls": max_model_calls,
                    "seen_candidates": seen_candidates,
                    "max_candidates": max_candidates,
                    "frontier_size": len(frontier),
                    "subgoal_count": subgoal_count,
                },
            )
        if model_calls >= max_model_calls:
            action = "stop"
            reason = "model-call budget exhausted"
        elif seen_candidates >= max_candidates:
            action = "stop"
            reason = "candidate budget exhausted"
        else:
            action = "continue"
            reason = (
                "assign proposer roles to frontier nodes"
                if frontier else "start root search with all proposer roles"
            )
        return SupervisorDecision(
            id=f"supervisor-r{round_number}",
            round=round_number,
            action=action,
            reason=reason,
            assignments={
                role: (
                    frontier[index % len(frontier)].id
                    if frontier else None
                )
                for index, role in enumerate(self.roles)
            } if action == "continue" else {},
            budget_state={
                "model_calls": model_calls,
                "max_model_calls": max_model_calls,
                "seen_candidates": seen_candidates,
                "max_candidates": max_candidates,
                "frontier_size": len(frontier),
                "subgoal_count": subgoal_count,
            },
        )

    def assign(
        self,
        *,
        round_number: int,
        frontier: list[SearchNode],
        open_handoffs: list[Handoff],
    ) -> list[AgentAssignment]:
        assignments: list[AgentAssignment] = []
        by_target = {
            handoff.to_agent: handoff
            for handoff in open_handoffs
            if not handoff.accepted
        }
        node_by_id = {node.id: node for node in frontier}
        for index, role in enumerate(self.roles):
            handoff = by_target.get(role)
            parent = None
            if handoff is not None:
                parent = node_by_id.get(handoff.node_id)
                if parent is not None:
                    handoff.accepted = True
            if parent is None and frontier:
                parent = frontier[index % len(frontier)]
            assignments.append(AgentAssignment(role=role, parent=parent, handoff=handoff))
        return assignments

    def create_handoffs(
        self,
        *,
        round_number: int,
        frontier: list[SearchNode],
    ) -> list[Handoff]:
        handoffs: list[Handoff] = []
        if not frontier:
            return handoffs
        for index, node in enumerate(frontier):
            from_agent = node.candidate.agent
            try:
                start = self.roles.index(from_agent) + 1
            except ValueError:
                start = index + 1
            to_agent = self.roles[start % len(self.roles)]
            reason = (
                "frontier node retained for repair after Lean diagnostics"
                if node.status != "verified"
                else "verified node retained as terminal evidence"
            )
            summary = summarize_node(node)
            handoffs.append(Handoff(
                id=f"handoff-r{round_number}-{index + 1}",
                round=round_number,
                from_agent=from_agent,
                to_agent=to_agent,
                node_id=node.id,
                reason=reason,
                state_summary=summary,
            ))
        return handoffs


def summarize_node(node: SearchNode) -> str:
    diagnostics = " ".join(node.diagnostics.split())
    if len(diagnostics) > 240:
        diagnostics = diagnostics[:237] + "..."
    return (
        f"{node.id}: status={node.status}, score={node.score:.2f}, "
        f"depth={node.depth}, diagnostics={diagnostics or '(none)'}"
    )


def agent_scorecard(turns: list[AgentTurn], attempts: list[Attempt]) -> dict[str, Any]:
    by_agent: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "turns": 0,
        "candidate_count": 0,
        "verified": 0,
        "lean_error": 0,
        "timeout_or_worker_failure": 0,
        "provider_errors": 0,
    })
    for turn in turns:
        stats = by_agent[turn.agent]
        stats["turns"] += 1
        stats["candidate_count"] += len(turn.candidate_ids)
        if turn.status == "provider_error":
            stats["provider_errors"] += 1
    for attempt in attempts:
        stats = by_agent[attempt.candidate.agent]
        if attempt.status == "verified":
            stats["verified"] += 1
        elif attempt.status == "lean_error":
            stats["lean_error"] += 1
        elif attempt.status in {"timeout", "memory_limit", "worker_failure"}:
            stats["timeout_or_worker_failure"] += 1
    for stats in by_agent.values():
        checked = stats["verified"] + stats["lean_error"] + stats["timeout_or_worker_failure"]
        stats["success_rate"] = stats["verified"] / checked if checked else 0.0
    return dict(sorted(by_agent.items()))
