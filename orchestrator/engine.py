from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import (
    AgentTurn,
    Attempt,
    Candidate,
    Handoff,
    SearchNode,
    SearchTask,
    SupervisorDecision,
)
from .frontier import FrontierPolicy, restore_search
from .providers import LlmProvider, ProviderError
from .supervisor import AgentAssignment, SupervisorPolicy, agent_scorecard
from .verifier import VerifierClient, VerifierError


DEFAULT_ROLES_FILE = Path(__file__).with_name("roles.json")


def load_roles(path: str | Path = DEFAULT_ROLES_FILE) -> dict[str, str]:
    with Path(path).open(encoding="utf-8") as file:
        value = json.load(file)
    if not isinstance(value, dict) or not value or any(
        not isinstance(name, str) or not name or not isinstance(instruction, str) or not instruction
        for name, instruction in value.items()
    ):
        raise ValueError("roles file must be a non-empty object of name/instruction strings")
    return value

PROPOSAL_SCHEMA = {
    "type": "object",
    "required": ["candidates"],
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object", "required": ["patch"],
                "properties": {
                    "patch": {"type": "string"},
                    "rationale": {"type": "string"},
                    "progress_summary": {"type": "string"},
                },
            },
        }
    },
}

CRITIC_SCHEMA = {
    "type": "object",
    "required": ["ordered_ids"],
    "properties": {
        "ordered_ids": {"type": "array", "items": {"type": "string"}},
        "feedback": {"type": "string"},
    },
}


@dataclass(slots=True)
class SearchConfig:
    max_rounds: int = 3
    candidates_per_agent: int = 2
    max_parallel_verifications: int = 4
    max_agent_parallelism: int = 3
    max_model_calls: int = 20
    max_total_candidates: int = 24
    stop_on_first_success: bool = True
    frontier_width: int = 6
    proposer_roles: dict[str, str] = field(default_factory=load_roles)

    def __post_init__(self) -> None:
        numeric = (
            self.max_rounds, self.candidates_per_agent, self.max_parallel_verifications,
            self.max_agent_parallelism, self.max_model_calls, self.max_total_candidates,
            self.frontier_width,
        )
        if any(value <= 0 for value in numeric):
            raise ValueError("all orchestration budgets must be positive")
        if not self.proposer_roles or any(not name or not instruction
                                          for name, instruction in self.proposer_roles.items()):
            raise ValueError("at least one configured proposer role is required")


class Orchestrator:
    def __init__(self, provider: LlmProvider, verifier: VerifierClient,
                 config: SearchConfig | None = None):
        self.provider = provider
        self.verifier = verifier
        self.config = config or SearchConfig()
        self.frontier_policy = FrontierPolicy(self.config.frontier_width)
        self.supervisor = SupervisorPolicy(list(self.config.proposer_roles))
        self._budget_lock = threading.Lock()
        self._model_calls = 0

    def _complete(self, **request: Any) -> dict[str, Any]:
        with self._budget_lock:
            if self._model_calls >= self.config.max_model_calls:
                raise ProviderError("model-call budget exhausted")
            self._model_calls += 1
        return self.provider.complete(**request)

    def _proposal_prompt(self, task: SearchTask, role: str, round_number: int,
                         attempts: list[Attempt], parent: SearchNode | None,
                         frontier: list[SearchNode]) -> str:
        history = [
            {"patch": item.candidate.patch, "status": item.status,
             "diagnostics": item.diagnostics[-3000:]}
            for item in attempts[-8:]
        ]
        inherited = (
            {
                "node_id": parent.id,
                "patch": parent.candidate.patch,
                "diagnostics": parent.diagnostics[-6000:],
                "progress_summary": parent.candidate.progress_summary,
                "score": parent.score,
            }
            if parent else None
        )
        alternatives = [
            {
                "node_id": node.id, "patch": node.candidate.patch,
                "diagnostics": node.diagnostics[-1500:], "score": node.score,
            }
            for node in frontier[:3] if parent is None or node.id != parent.id
        ]
        return (
            f"Verification mode: {task.verification_mode}\n"
            f"Target declaration: {task.target or '(generated statement below)'}\n"
            f"Theorem statement: {task.theorem}\n"
            f"Project context:\n{task.context or '(none supplied)'}\n\n"
            f"Task decomposition/subgoal DAG:\n"
            f"{json.dumps(task.subgoals, ensure_ascii=False)}\n\n"
            f"This is search round {round_number}. Strategy: {self.config.proposer_roles[role]}\n"
            f"Previous verified outcomes:\n{json.dumps(history, ensure_ascii=False)}\n\n"
            f"Inherited frontier node:\n{json.dumps(inherited, ensure_ascii=False)}\n"
            f"Alternative frontier nodes:\n{json.dumps(alternatives, ensure_ascii=False)}\n\n"
            f"Return up to {self.config.candidates_per_agent} complete Lean proof-body patches. "
            "When an inherited node exists, repair or extend that proof using its exact Lean "
            "diagnostics; return the entire replacement proof body, not a diff. "
            "Each patch must normally begin with `by`. Never use `sorry`, `admit`, or unsafe axioms. "
            "Return only a JSON object matching the supplied schema."
        )

    def _propose(self, task: SearchTask, role: str, round_number: int,
                 attempts: list[Attempt], parent: SearchNode | None,
                 frontier: list[SearchNode],
                 handoff: Handoff | None) -> tuple[str, SearchNode | None, Handoff | None, dict[str, Any] | None, str | None]:
        system = (
            "You are a Lean 4 proof-search proposer. Generate proof bodies for an external "
            "authoritative Lean checker; do not claim success yourself."
        )
        try:
            response = self._complete(
                agent=f"proposer:{role}", system=system,
                prompt=self._proposal_prompt(
                    task, role, round_number, attempts, parent, frontier
                ),
                schema=PROPOSAL_SCHEMA,
            )
            return role, parent, handoff, response, None
        except ProviderError as error:
            return role, parent, handoff, None, str(error)

    def _collect_candidates(self, task: SearchTask, round_number: int,
                            attempts: list[Attempt], seen: set[str],
                            events: list[dict[str, Any]],
                            frontier: list[SearchNode],
                            assignments: list[AgentAssignment],
                            turns: list[AgentTurn]) -> list[Candidate]:
        roles = self.config.proposer_roles
        results: dict[str, tuple[SearchNode | None, Handoff | None, dict[str, Any] | None, str | None]] = {}
        with ThreadPoolExecutor(max_workers=min(self.config.max_agent_parallelism, len(assignments))) as pool:
            futures = [
                pool.submit(
                    self._propose, task, assignment.role, round_number, attempts,
                    assignment.parent, frontier, assignment.handoff,
                )
                for assignment in assignments
            ]
            for future in futures:
                role, parent, handoff, response, error = future.result()
                results[role] = (parent, handoff, response, error)
        candidates: list[Candidate] = []
        for role in roles:
            parent, handoff, response, error = results[role]
            turn = AgentTurn(
                id=f"{task.id}-turn-r{round_number}-{role}",
                round=round_number,
                agent=role,
                role=role,
                action="propose_proof_patch",
                status="completed",
                parent_node_id=parent.id if parent else None,
                received_handoff_id=handoff.id if handoff else None,
                input_summary=(
                    f"inherited {parent.id} with status {parent.status}"
                    if parent else "root proof search"
                ),
            )
            if error:
                events.append({"type": "provider_error", "round": round_number,
                               "agent": role, "message": error})
                turn.status = "provider_error"
                turn.error = error
                turn.output_summary = "provider did not return candidates"
                turns.append(turn)
                events.append({"type": "agent_turn_completed", **turn.to_json()})
                continue
            raw_candidates = response.get("candidates", []) if isinstance(response, dict) else []
            if not isinstance(raw_candidates, list):
                events.append({"type": "invalid_agent_output", "round": round_number,
                               "agent": role, "message": "candidates was not an array"})
                turn.status = "invalid_output"
                turn.error = "candidates was not an array"
                turns.append(turn)
                events.append({"type": "agent_turn_completed", **turn.to_json()})
                continue
            accepted = 0
            for item in raw_candidates:
                if accepted >= self.config.candidates_per_agent or not isinstance(item, dict):
                    continue
                patch = item.get("patch")
                if not isinstance(patch, str) or not patch.strip() or patch in seen:
                    continue
                if "sorry" in patch or "admit" in patch:
                    events.append({"type": "rejected_placeholder", "round": round_number,
                                   "agent": role})
                    continue
                seen.add(patch)
                rationale = item.get("rationale", "")
                progress = item.get("progress_summary", "")
                candidate_id = f"{task.id}-r{round_number}-{role}-{accepted + 1}"
                candidates.append(Candidate(
                    id=candidate_id, patch=patch,
                    rationale=rationale if isinstance(rationale, str) else "",
                    agent=role, round=round_number,
                    parent_node_id=parent.id if parent else None,
                    progress_summary=progress if isinstance(progress, str) else "",
                ))
                turn.candidate_ids.append(candidate_id)
                accepted += 1
                if len(seen) >= self.config.max_total_candidates:
                    turn.output_summary = f"accepted {accepted} candidate(s); candidate budget reached"
                    turns.append(turn)
                    events.append({"type": "agent_turn_completed", **turn.to_json()})
                    return candidates
            turn.status = "no_candidates" if accepted == 0 else "completed"
            turn.output_summary = f"accepted {accepted} candidate(s)"
            turns.append(turn)
            if handoff is not None and handoff.accepted:
                events.append({"type": "handoff_accepted", **handoff.to_json()})
            events.append({"type": "agent_turn_completed", **turn.to_json()})
        return candidates

    def _rank(self, task: SearchTask, candidates: list[Candidate], round_number: int,
              events: list[dict[str, Any]]) -> list[Candidate]:
        if len(candidates) < 2:
            return candidates
        prompt = (
            f"Theorem: {task.theorem}\nTarget: {task.target}\n"
            "Rank the following proposed Lean patches from most likely to compile to least likely. "
            "Do not rewrite them. Include every candidate ID exactly once.\n" +
            json.dumps([candidate.to_json() for candidate in candidates], ensure_ascii=False)
        )
        try:
            response = self._complete(
                agent="critic",
                system="You are a conservative Lean 4 proof critic. Rank candidates; Lean is the final judge.",
                prompt=prompt, schema=CRITIC_SCHEMA,
            )
        except ProviderError as error:
            events.append({"type": "provider_error", "round": round_number,
                           "agent": "critic", "message": str(error)})
            return candidates
        by_id = {candidate.id: candidate for candidate in candidates}
        order = response.get("ordered_ids", [])
        ranked = [by_id.pop(identifier) for identifier in order
                  if isinstance(identifier, str) and identifier in by_id] if isinstance(order, list) else []
        ranked.extend(candidate for candidate in candidates if candidate.id in by_id)
        events.append({"type": "critic", "round": round_number,
                       "feedback": response.get("feedback", ""),
                       "order": [candidate.id for candidate in ranked]})
        return ranked

    def search(self, task: SearchTask,
               resume: dict[str, Any] | None = None) -> dict[str, Any]:
        self._model_calls = 0
        attempts: list[Attempt] = []
        events: list[dict[str, Any]] = list(resume.get("events", [])) if resume else []
        turns: list[AgentTurn] = []
        handoffs: list[Handoff] = []
        supervisor_decisions: list[SupervisorDecision] = []
        seen: set[str] = set()
        winner: Candidate | None = None
        graph_nodes: list[SearchNode] = []
        frontier: list[SearchNode] = []
        if resume:
            restored = restore_search(resume, self.frontier_policy)
            attempts = restored.attempts
            graph_nodes = restored.nodes
            frontier = restored.frontier
            seen = restored.seen_patches
            winner = restored.winner
            for raw in resume.get("agent_turns", []):
                if isinstance(raw, dict):
                    try:
                        turns.append(AgentTurn(**raw))
                    except TypeError:
                        pass
            for raw in resume.get("handoffs", []):
                if isinstance(raw, dict):
                    try:
                        handoffs.append(Handoff(**raw))
                    except TypeError:
                        pass
            for raw in resume.get("supervisor_decisions", []):
                if isinstance(raw, dict):
                    try:
                        supervisor_decisions.append(SupervisorDecision(**raw))
                    except TypeError:
                        pass
            events.append({
                "type": "search_resumed",
                "node_count": len(graph_nodes),
                "frontier": [node.id for node in frontier],
            })
        final_status = "exhausted"
        first_round = max(
            (node.candidate.round for node in graph_nodes), default=0
        ) + 1
        if winner is not None:
            final_status = "verified"
        for round_number in range(first_round, first_round + self.config.max_rounds):
            if winner is not None:
                break
            decision = self.supervisor.decide(
                round_number=round_number,
                model_calls=self._model_calls,
                max_model_calls=self.config.max_model_calls,
                seen_candidates=len(seen),
                max_candidates=self.config.max_total_candidates,
                winner_present=winner is not None,
                frontier=frontier,
                subgoal_count=len(task.subgoals),
            )
            supervisor_decisions.append(decision)
            events.append({"type": "supervisor_decision", **decision.to_json()})
            if decision.action == "stop":
                final_status = (
                    "model_budget_exhausted"
                    if "model-call" in decision.reason else
                    "candidate_budget_exhausted"
                    if "candidate" in decision.reason else
                    final_status
                )
                break
            if len(seen) >= self.config.max_total_candidates:
                final_status = "candidate_budget_exhausted"
                break
            assignments = self.supervisor.assign(
                round_number=round_number,
                frontier=frontier,
                open_handoffs=handoffs,
            )
            candidates = self._collect_candidates(
                task, round_number, attempts, seen, events, frontier, assignments, turns
            )
            candidates = self._rank(task, candidates, round_number, events)
            if not candidates:
                if self._model_calls >= self.config.max_model_calls:
                    final_status = "model_budget_exhausted"
                    break
                events.append({"type": "empty_round", "round": round_number})
                continue
            try:
                verifier_request = {
                    "request_id": f"{task.id}-round-{round_number}",
                    "project": task.project,
                    "module": task.module,
                    "declaration": task.theorem,
                    "candidates": [
                        {"id": item.id, "patch": item.patch} for item in candidates
                    ],
                    "max_parallel": self.config.max_parallel_verifications,
                    "stop_on_first_success": self.config.stop_on_first_success,
                    "limits": task.limits,
                    "parent_attempt_id": task.parent_attempt_id,
                }
                if task.verification_mode == "generated_obligation":
                    response = self.verifier.verify_generated_batch(
                        **verifier_request, preamble=task.preamble
                    )
                else:
                    response = self.verifier.verify_batch(
                        **verifier_request, target=task.target
                    )
            except VerifierError as error:
                events.append({"type": "verifier_error", "round": round_number,
                               "message": str(error)})
                final_status = "verifier_error"
                break
            candidate_by_id = {candidate.id: candidate for candidate in candidates}
            for critic_rank, result in enumerate(response.get("results", [])):
                if not isinstance(result, dict) or result.get("id") not in candidate_by_id:
                    continue
                candidate = candidate_by_id[result["id"]]
                attempt = Attempt(
                    candidate=candidate, status=str(result.get("status", "worker_failure")),
                    diagnostics=str(result.get("diagnostics", "")),
                    elapsed_ms=int(result.get("elapsed_ms", 0)), cached=bool(result.get("cached", False)),
                )
                attempts.append(attempt)
                parent = next(
                    (node for node in graph_nodes if node.id == candidate.parent_node_id),
                    None,
                )
                graph_nodes.append(SearchNode(
                    id=candidate.id,
                    parent_id=candidate.parent_node_id,
                    candidate=candidate,
                    status=attempt.status,
                    diagnostics=attempt.diagnostics,
                    score=self.frontier_policy.score(
                        attempt.status, attempt.diagnostics, critic_rank
                    ),
                    depth=(parent.depth + 1) if parent else 1,
                ))
                if winner is None and attempt.status == "verified":
                    winner = candidate
            events.append({"type": "verification_round", "round": round_number,
                           "status": response.get("status", "unknown"),
                           "attempt_count": len(candidates)})
            frontier = self.frontier_policy.select(graph_nodes)
            events.append({
                "type": "frontier_update", "round": round_number,
                "node_ids": [node.id for node in frontier],
            })
            new_handoffs = self.supervisor.create_handoffs(
                round_number=round_number,
                frontier=[node for node in frontier if node.status != "verified"],
            )
            handoffs.extend(new_handoffs)
            for handoff in new_handoffs:
                events.append({"type": "handoff_created", **handoff.to_json()})
            if winner:
                final_status = "verified"
                break
        output: dict[str, Any] = {
            "version": 1, "id": task.id, "status": final_status,
            "target": task.target, "rounds_used": max((item.candidate.round for item in attempts), default=0),
            "model_calls": self._model_calls, "unique_candidates": len(seen),
            "attempts": [attempt.to_json() for attempt in attempts], "events": events,
            "agent_turns": [turn.to_json() for turn in turns],
            "handoffs": [handoff.to_json() for handoff in handoffs],
            "supervisor_decisions": [
                decision.to_json() for decision in supervisor_decisions
            ],
            "agent_scorecard": agent_scorecard(turns, attempts),
            "search_graph": {
                "nodes": [node.to_json() for node in graph_nodes],
                "frontier": [node.id for node in frontier],
            },
        }
        if winner:
            output["winner"] = winner.to_json()
        return output
