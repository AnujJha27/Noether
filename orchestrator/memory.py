from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import Attempt


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _append_unique(items: list[str], value: str, *, limit: int = 50) -> None:
    value = value.strip()
    if value and value not in items:
        items.append(value)
        del items[:-limit]


@dataclass(slots=True)
class RunMemory:
    known_failed_tactics: list[str] = field(default_factory=list)
    useful_lemmas: list[str] = field(default_factory=list)
    successful_proof_patterns: list[str] = field(default_factory=list)
    theorem_notes: list[str] = field(default_factory=list)
    agent_score_history: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, value: Any) -> "RunMemory":
        if not isinstance(value, dict):
            return cls()
        scores = value.get("agent_score_history", {})
        return cls(
            known_failed_tactics=_strings(value.get("known_failed_tactics")),
            useful_lemmas=_strings(value.get("useful_lemmas")),
            successful_proof_patterns=_strings(value.get("successful_proof_patterns")),
            theorem_notes=_strings(value.get("theorem_notes")),
            agent_score_history=scores if isinstance(scores, dict) else {},
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "known_failed_tactics": list(self.known_failed_tactics),
            "useful_lemmas": list(self.useful_lemmas),
            "successful_proof_patterns": list(self.successful_proof_patterns),
            "theorem_notes": list(self.theorem_notes),
            "agent_score_history": dict(self.agent_score_history),
        }

    def prompt_summary(self) -> str:
        parts: list[str] = []
        if self.known_failed_tactics:
            parts.append("Known failed tactics/patches: " + "; ".join(self.known_failed_tactics[-8:]))
        if self.useful_lemmas:
            parts.append("Useful lemmas/facts: " + "; ".join(self.useful_lemmas[-8:]))
        if self.successful_proof_patterns:
            parts.append("Successful proof patterns: " + "; ".join(self.successful_proof_patterns[-8:]))
        if self.theorem_notes:
            parts.append("Theorem-specific notes: " + "; ".join(self.theorem_notes[-8:]))
        if self.agent_score_history:
            parts.append("Agent score history: " + str(self.agent_score_history))
        return "\n".join(parts) if parts else "(no run memory yet)"

    def update_from_attempts(self, attempts: list[Attempt]) -> None:
        for attempt in attempts[-12:]:
            patch = " ".join(attempt.candidate.patch.split())
            diagnostics = " ".join(attempt.diagnostics.split())
            if attempt.status == "verified":
                _append_unique(
                    self.successful_proof_patterns,
                    f"{attempt.candidate.agent}: {patch[:220]}",
                )
                continue
            if attempt.status == "lean_error":
                note = patch[:160]
                if diagnostics:
                    note += f" -> {diagnostics[:180]}"
                _append_unique(self.known_failed_tactics, note)
                continue
            if attempt.status in {"timeout", "memory_limit", "worker_failure", "project_not_built"}:
                _append_unique(
                    self.theorem_notes,
                    f"{attempt.candidate.id} ended with {attempt.status}",
                )

    def update_from_scorecard(self, scorecard: dict[str, Any]) -> None:
        self.agent_score_history = scorecard
