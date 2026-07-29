from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from orchestrator.verifier import VerifierClient

from .certificate import project_fingerprint
from .policy import Policy


class ContextError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ContextKey:
    project_fingerprint: str
    toolchain_fingerprint: str
    policy_fingerprint: str

    @property
    def cache_namespace(self) -> str:
        digest = hashlib.sha256(
            (
                f"{self.project_fingerprint}\0{self.toolchain_fingerprint}\0"
                f"{self.policy_fingerprint}"
            ).encode()
        ).hexdigest()
        return digest[:24]


@dataclass(slots=True)
class WorkerContext:
    key: ContextKey
    policy: Policy
    project_root: Path
    verifier: VerifierClient


class WorkerContextRegistry:
    """Creates exactly one persistent verifier for each immutable context key."""

    def __init__(self, *, verifier_command: Sequence[str],
                 service_cwd: str | Path, cache_dir: str | Path,
                 lake_executable: str | None = None):
        if not verifier_command:
            raise ValueError("verifier_command cannot be empty")
        self.verifier_command = list(verifier_command)
        self.service_cwd = Path(service_cwd).resolve()
        self.cache_dir = Path(cache_dir).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.lake_executable = lake_executable
        self._contexts: dict[ContextKey, WorkerContext] = {}
        self._lock = threading.Lock()

    def _key(self, policy: Policy, project_root: Path) -> ContextKey:
        try:
            toolchain = (project_root / "lean-toolchain").read_text(encoding="utf-8").strip()
        except OSError as error:
            raise ContextError(f"cannot read project toolchain: {error}") from error
        if toolchain != policy.toolchain:
            raise ContextError(
                f"policy requires {policy.toolchain!r}, project has {toolchain!r}"
            )
        return ContextKey(
            project_fingerprint=project_fingerprint(project_root),
            toolchain_fingerprint=hashlib.sha256(toolchain.encode()).hexdigest(),
            policy_fingerprint=hashlib.sha256(policy.source_path.read_bytes()).hexdigest(),
        )

    def get(self, policy: Policy, project_root: str | Path) -> WorkerContext:
        project = Path(project_root).resolve()
        key = self._key(policy, project)
        with self._lock:
            existing = self._contexts.get(key)
            if existing is not None:
                return existing
            environment = os.environ.copy()
            environment["PROOF_SEARCH_PROJECT_DIR"] = str(project)
            environment["PROOF_SEARCH_DB"] = str(
                self.cache_dir / f"{key.cache_namespace}.sqlite3"
            )
            if self.lake_executable:
                environment["PROOF_SEARCH_LAKE"] = self.lake_executable
            verifier = VerifierClient(
                self.verifier_command, cwd=self.service_cwd, env=environment
            )
            verifier.start()
            context = WorkerContext(
                key=key, policy=policy, project_root=project, verifier=verifier
            )
            self._contexts[key] = context
            return context

    def close(self) -> None:
        with self._lock:
            contexts = list(self._contexts.values())
            self._contexts.clear()
        for context in contexts:
            context.verifier.close()

    def __enter__(self) -> "WorkerContextRegistry":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
