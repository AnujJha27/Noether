from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import Attempt, Candidate, SearchNode


@dataclass(frozen=True, slots=True)
class FrontierPolicy:
    width: int

    def score(self, status: str, diagnostics: str, critic_rank: int) -> float:
        if status == "verified":
            return 1_000_000.0
        unsolved = diagnostics.lower().count("unsolved goals")
        goals = diagnostics.count("⊢")
        errors = diagnostics.lower().count("error:")
        timeout_penalty = (
            500 if status in {"timeout", "memory_limit", "worker_failure"} else 0
        )
        return (
            1000.0
            - 160.0 * unsolved
            - 35.0 * goals
            - 25.0 * errors
            - min(len(diagnostics), 20_000) / 1000.0
            - timeout_penalty
            - critic_rank
        )

    def select(self, nodes: list[SearchNode]) -> list[SearchNode]:
        ordered = sorted(nodes, key=lambda node: (-node.score, node.depth, node.id))
        frontier: list[SearchNode] = []
        patches: set[str] = set()
        for node in ordered:
            if node.candidate.patch in patches:
                continue
            patches.add(node.candidate.patch)
            frontier.append(node)
            if len(frontier) >= self.width:
                break
        return frontier


@dataclass(slots=True)
class RestoredSearch:
    attempts: list[Attempt]
    nodes: list[SearchNode]
    frontier: list[SearchNode]
    seen_patches: set[str]
    winner: Candidate | None


def restore_search(value: dict[str, Any], policy: FrontierPolicy) -> RestoredSearch:
    attempts: list[Attempt] = []
    nodes: list[SearchNode] = []
    seen: set[str] = set()
    winner = None
    for raw in value.get("search_graph", {}).get("nodes", []):
        candidate_value = raw.get("candidate", {})
        try:
            candidate = Candidate(**candidate_value)
            node = SearchNode(
                id=raw["id"],
                parent_id=raw.get("parent_id"),
                candidate=candidate,
                status=raw["status"],
                diagnostics=raw.get("diagnostics", ""),
                score=float(raw["score"]),
                depth=int(raw["depth"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("resume search graph is malformed") from error
        nodes.append(node)
        seen.add(candidate.patch)
        attempts.append(
            Attempt(candidate=candidate, status=node.status, diagnostics=node.diagnostics)
        )
        if node.status == "verified" and winner is None:
            winner = candidate
    frontier_ids = set(value.get("search_graph", {}).get("frontier", []))
    frontier = [node for node in nodes if node.id in frontier_ids]
    if not frontier:
        frontier = policy.select(nodes)
    return RestoredSearch(attempts, nodes, frontier, seen, winner)

