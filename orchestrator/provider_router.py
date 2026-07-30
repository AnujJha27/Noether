from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .agents import AgentSpec
from .providers import LlmProvider


@dataclass(slots=True)
class ProviderRouter:
    default_provider: LlmProvider
    by_model: dict[str, LlmProvider] | None = None

    def provider_for(self, agent: AgentSpec) -> LlmProvider:
        if self.by_model and agent.model in self.by_model:
            return self.by_model[agent.model]
        return self.default_provider

    def complete(self, agent: AgentSpec, *, system: str, prompt: str,
                 schema: dict[str, Any]) -> dict[str, Any]:
        return self.provider_for(agent).complete(
            agent=agent.name,
            system=system,
            prompt=prompt,
            schema=schema,
        )
